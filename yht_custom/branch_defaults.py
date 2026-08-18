# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Branch-derived document defaults.

Two hooks, both registered against ``*`` and both cheap no-ops for the doctypes
they do not care about:

``apply_branch_defaults`` (before_validate)
    Replaces a cost center the user cannot see with their branch's own. Without
    it, a global default cost center makes every new document fail on a User
    Permission the operator cannot even see.

``set_naming_series_from_branch`` (before_insert)
    Picks the branch's series for the doctype, so a Khobar user cannot mint a
    document under another branch's counter.
"""

import frappe
from frappe.utils import cint

#: Doctypes whose cost center we override for branch users.
COST_CENTER_DOCTYPES = (
	"Sales Invoice",
	"Purchase Invoice",
	"Payment Entry",
	"Delivery Note",
	"Purchase Receipt",
	"Sales Order",
	"Quotation",
)

#: Roles trusted to pick their own cost center and series.
BYPASS_ROLES = ("System Manager", "Stock Manager", "Sales Manager", "Sales Master Manager", "Accounts Manager")


def _is_bypass(user=None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(frappe.get_roles(user)) & set(BYPASS_ROLES))


def _user_branch_config(user=None):
	"""The user's Branch Configuration name, or None. Cached per request."""
	user = user or frappe.session.user
	cache = frappe.local.yht_branch_config_cache = getattr(frappe.local, "yht_branch_config_cache", {})
	if user in cache:
		return cache[user]

	configs = frappe.get_all("Branch Configuration User", filters={"user": user}, pluck="parent", limit=1)
	cache[user] = configs[0] if configs else None
	return cache[user]


# --------------------------------------------------------------- cost centers


def apply_branch_defaults(doc, method=None):
	"""Stamp the branch's cost center onto the header and item rows."""
	if doc.doctype not in COST_CENTER_DOCTYPES:
		return
	if _is_bypass():
		return

	config = _user_branch_config()
	if not config:
		return

	cost_center = frappe.db.get_value(
		"Branch Configuration Cost Center", {"parent": config}, "cost_center", order_by="idx asc"
	)
	if not cost_center:
		return

	if doc.meta.has_field("cost_center"):
		doc.cost_center = cost_center

	# Item rows carry their own cost center and are what actually reaches the GL.
	for row in doc.get("items") or []:
		if row.meta.has_field("cost_center"):
			row.cost_center = cost_center


# -------------------------------------------------------------- naming series


def set_naming_series_from_branch(doc, method=None):
	"""Override ``naming_series`` with the one configured for the user's branch.

	Deliberately overrides whatever the form pre-filled: the picker lists every
	branch's templates, so leaving the form's choice alone lets a Khobar user
	consume another branch's counter. Two exceptions:

	* the series already starts with this branch's prefix — the operator picked
	  it on purpose
	* the user holds a bypass role
	"""
	if not doc.meta.has_field("naming_series"):
		return
	if _is_bypass():
		return

	config = _user_branch_config()
	if not config:
		return

	branch = frappe.db.get_value("Branch Configuration", config, "branch")
	if not branch:
		return

	prefix = frappe.db.get_value("Branch", branch, "custom_doc_prefix") or ""
	if prefix and (doc.get("naming_series") or "").startswith(prefix):
		return

	is_return = cint(doc.get("is_return"))
	rows = frappe.get_all(
		"Branch Naming Series",
		filters={"parent": branch, "parent_doctype": doc.doctype},
		fields=["naming_series", "use_for_return"],
	)
	if not rows:
		return

	match = next((r for r in rows if cint(r.use_for_return) == is_return), None)
	if match:
		doc.naming_series = match.naming_series
