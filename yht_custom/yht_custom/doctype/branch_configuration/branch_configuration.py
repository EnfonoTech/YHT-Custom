# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Branch Configuration — the single operator-facing switch for a branch.

Saving one row provisions everything a branch user needs:

* ``User Permission`` rows for Company / Branch / Warehouse / Cost Center
* a ``System User`` upgrade, because Website Users silently lose desk roles
* the chosen role, inserted directly as ``Has Role``
* the Module Profile that trims the desk sidebar

Editing the row reverses cleanly: users dropped from the table lose the
permissions this branch granted them, and lose the role unless another Branch
Configuration still assigns it.
"""

import frappe
from frappe import _
from frappe.model.document import Document

#: Roles a Branch Configuration row may hand out. Anything else is rejected so a
#: typo in the child table cannot grant an arbitrary role.
ASSIGNABLE_ROLES = ("Branch User", "Stock User", "Stock Manager")

#: Module Profile applied per role, trimming the desk sidebar.
MODULE_PROFILE_BY_ROLE = {
	"Branch User": "Branch User",
	"Stock User": "Branch User",
	"Stock Manager": None,  # Stock Managers keep the full sidebar
}

ALLOW_TYPES = ("Company", "Branch", "Warehouse", "Cost Center")


class BranchConfiguration(Document):
	def validate(self):
		self.validate_child_companies()
		self.validate_roles()
		self.validate_duplicate_users()

	def before_save(self):
		self.revoke_for_removed_users()

	def on_update(self):
		self.create_permissions()

	# ------------------------------------------------------------------ validate

	def validate_child_companies(self):
		"""Every warehouse and cost center must belong to this row's Company.

		Caught here rather than at posting time — a mismatched cost center only
		surfaces as an opaque "not permitted" much later.
		"""
		for table, fieldname, label in (
			("warehouse", "warehouse", _("Warehouse")),
			("cost_center", "cost_center", _("Cost Center")),
		):
			for row in self.get(table) or []:
				value = row.get(fieldname)
				if not value:
					continue
				actual = frappe.db.get_value(row.meta.get_field(fieldname).options, value, "company")
				if actual and actual != self.company:
					frappe.throw(
						_("Row {0}: {1} {2} belongs to company {3}, but this Branch Configuration is for {4}.").format(
							row.idx, label, frappe.bold(value), frappe.bold(actual), frappe.bold(self.company)
						)
					)

	def validate_roles(self):
		for row in self.get("user") or []:
			if row.role not in ASSIGNABLE_ROLES:
				frappe.throw(
					_("Row {0}: role {1} cannot be assigned from a Branch Configuration. Allowed: {2}.").format(
						row.idx, frappe.bold(row.role), ", ".join(ASSIGNABLE_ROLES)
					)
				)

	def validate_duplicate_users(self):
		seen = set()
		for row in self.get("user") or []:
			if row.user in seen:
				frappe.throw(_("Row {0}: user {1} is listed twice.").format(row.idx, frappe.bold(row.user)))
			seen.add(row.user)

	# ----------------------------------------------------------------- provision

	def create_permissions(self):
		"""Grant Company / Branch / Warehouse / Cost Center permissions per user."""
		warehouses = [r.warehouse for r in (self.get("warehouse") or []) if r.warehouse]
		cost_centers = [r.cost_center for r in (self.get("cost_center") or []) if r.cost_center]
		company_default_cc = frappe.db.get_value("Company", self.company, "cost_center")

		for row in self.get("user") or []:
			if not row.user:
				continue

			_ensure_system_user(row.user)

			# Company — default so forms do not pick up a company the user cannot see.
			_grant(row.user, "Company", self.company, is_default=not _has_default(row.user, "Company"))
			_grant(row.user, "Branch", self.branch)

			# First row of each table becomes the default; the rest grant access only.
			for idx, wh in enumerate(warehouses):
				_grant(row.user, "Warehouse", wh, is_default=(idx == 0 and not _has_default(row.user, "Warehouse")))
			for idx, cc in enumerate(cost_centers):
				_grant(row.user, "Cost Center", cc, is_default=(idx == 0 and not _has_default(row.user, "Cost Center")))

			# Tax templates hardcode the company default cost center, so the user
			# needs access to it even when it is not one of the branch's own.
			if company_default_cc and company_default_cc not in cost_centers:
				_grant(row.user, "Cost Center", company_default_cc, is_default=False)

			_assign_role(row.user, row.role)
			_set_module_profile(row.user, row.role)

	def revoke_for_removed_users(self):
		"""Withdraw what this branch granted from users dropped off the table."""
		if self.is_new():
			return

		before = self.get_doc_before_save()
		if not before:
			return

		old_users = {r.user: r.role for r in (before.get("user") or []) if r.user}
		new_users = {r.user: r.role for r in (self.get("user") or []) if r.user}

		for user, role in old_users.items():
			if user in new_users:
				continue
			_revoke_branch_permissions(user, before.company, before.branch, before)
			_maybe_remove_role(user, role, exclude_config=self.name)

		# Company changed: withdraw the old company from everyone still listed.
		if before.company and before.company != self.company:
			for user in new_users:
				frappe.db.delete("User Permission", {"user": user, "allow": "Company", "for_value": before.company})


# ---------------------------------------------------------------------- helpers


def _grant(user, allow, for_value, is_default=False):
	"""Idempotently create a User Permission row."""
	if not for_value:
		return

	existing = frappe.db.get_value(
		"User Permission", {"user": user, "allow": allow, "for_value": for_value}, ["name", "is_default"], as_dict=True
	)
	if existing:
		# Only ever promote to default, never demote — another branch may own it.
		if is_default and not existing.is_default:
			frappe.db.set_value("User Permission", existing.name, "is_default", 1)
		return

	doc = frappe.new_doc("User Permission")
	doc.user = user
	doc.allow = allow
	doc.for_value = for_value
	doc.is_default = 1 if is_default else 0
	doc.apply_to_all_doctypes = 1
	doc.insert(ignore_permissions=True)


def _has_default(user, allow):
	"""Frappe permits exactly one default per (user, allow type)."""
	return bool(frappe.db.exists("User Permission", {"user": user, "allow": allow, "is_default": 1}))


def _ensure_system_user(user):
	"""Website Users cannot hold desk roles — ``get_roles()`` comes back empty.

	Upgrade before inserting Has Role, or the role assignment silently does
	nothing and the user lands on a blank desk.
	"""
	if frappe.db.get_value("User", user, "user_type") == "Website User":
		frappe.db.set_value("User", user, "user_type", "System User")


def _assign_role(user, role):
	"""Insert Has Role directly.

	``user_doc.add_roles()`` can fail silently mid-save on a document that is
	already locked, so the child row goes in by hand.
	"""
	if not role or role not in ASSIGNABLE_ROLES:
		return
	if frappe.db.exists("Has Role", {"parent": user, "role": role}):
		return

	frappe.get_doc(
		{
			"doctype": "Has Role",
			"parent": user,
			"parenttype": "User",
			"parentfield": "roles",
			"role": role,
		}
	).insert(ignore_permissions=True)


def _set_module_profile(user, role):
	profile = MODULE_PROFILE_BY_ROLE.get(role)
	if not profile or not frappe.db.exists("Module Profile", profile):
		return
	# Direct DB write: saving the User doc here risks DocumentLockedError while
	# the Branch Configuration save is still in flight.
	frappe.db.set_value("User", user, "module_profile", profile, update_modified=False)


def _revoke_branch_permissions(user, company, branch, config):
	"""Delete the permissions a specific Branch Configuration granted."""
	frappe.db.delete("User Permission", {"user": user, "allow": "Branch", "for_value": branch})
	frappe.db.delete("User Permission", {"user": user, "allow": "Company", "for_value": company})

	for row in config.get("warehouse") or []:
		if row.warehouse:
			frappe.db.delete("User Permission", {"user": user, "allow": "Warehouse", "for_value": row.warehouse})
	for row in config.get("cost_center") or []:
		if row.cost_center:
			frappe.db.delete("User Permission", {"user": user, "allow": "Cost Center", "for_value": row.cost_center})


def _maybe_remove_role(user, role, exclude_config=None):
	"""Remove the role only if no other Branch Configuration still grants it."""
	filters = {"user": user, "role": role}
	others = frappe.get_all("Branch Configuration User", filters=filters, fields=["parent"])
	if any(o.parent != exclude_config for o in others):
		return
	frappe.db.delete("Has Role", {"parent": user, "role": role})


# ------------------------------------------------------------------ public APIs


@frappe.whitelist()
def get_branch_warehouses(branch: str) -> list[str]:
	"""Warehouses configured for a branch. Powers form filters and server guards."""
	if not branch:
		return []
	frappe.has_permission("Branch Configuration", "read", throw=True)
	configs = frappe.get_all("Branch Configuration", filters={"branch": branch}, pluck="name")
	if not configs:
		return []
	return frappe.get_all(
		"Branch Configuration Warehouse", filters={"parent": ["in", configs]}, pluck="warehouse"
	)


@frappe.whitelist()
def get_user_branch(user: str | None = None) -> dict:
	"""The branch context for a user: branch, warehouses, cost centers, company."""
	user = user or frappe.session.user
	if user != frappe.session.user:
		frappe.only_for(("System Manager", "Administrator"))

	configs = frappe.get_all("Branch Configuration User", filters={"user": user}, pluck="parent")
	if not configs:
		return {}

	rows = frappe.get_all(
		"Branch Configuration", filters={"name": ["in", configs]}, fields=["name", "branch", "company"]
	)
	return {
		"branches": [r.branch for r in rows],
		"companies": sorted({r.company for r in rows}),
		"warehouses": frappe.get_all(
			"Branch Configuration Warehouse", filters={"parent": ["in", configs]}, pluck="warehouse"
		),
		"cost_centers": frappe.get_all(
			"Branch Configuration Cost Center", filters={"parent": ["in", configs]}, pluck="cost_center"
		),
	}
