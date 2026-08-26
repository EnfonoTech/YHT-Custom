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


def _branch_series_rows(doctype: str):
	"""``(prefix, rows)`` for the calling user's branch, or ``("", [])``.

	``("", [])`` means "leave the form's choice alone": a bypass role, no branch
	configuration, or no series configured for this doctype.
	"""
	if _is_bypass():
		return "", []

	config = _user_branch_config()
	if not config:
		return "", []

	branch = frappe.db.get_value("Branch Configuration", config, "branch")
	if not branch:
		return "", []

	prefix = frappe.db.get_value("Branch", branch, "custom_doc_prefix") or ""
	rows = frappe.get_all(
		"Branch Naming Series",
		filters={"parent": branch, "parent_doctype": doctype},
		fields=["naming_series", "use_for_return"],
	)
	return prefix, rows


def configured_series(doctype: str, is_return=0) -> str | None:
	"""The series this user's branch will give a document of this flavour, or None.

	Exists so an entry point can SHOW the answer. The picker keeps the form's
	pre-filled invoice series after ``is_return`` is ticked, because the real choice
	happens here at ``before_insert`` — an operator who sees ``KSIN-`` and gets
	``KSCN-`` reads that as a bug.
	"""
	_prefix, rows = _branch_series_rows(doctype)
	match = next((r for r in rows if cint(r.use_for_return) == cint(is_return)), None)
	return match.naming_series if match else None


def set_naming_series_from_branch(doc, method=None):
	"""Override ``naming_series`` with the one configured for the user's branch.

	Deliberately overrides whatever the form pre-filled: the picker lists every
	branch's templates, so leaving the form's choice alone lets a Khobar user
	consume another branch's counter. Two exceptions:

	* the series is already this branch's series for this kind of document —
	  nothing to change — or it starts with this branch's prefix and is not the
	  branch's series for the OTHER return flavour, i.e. the operator picked it
	  on purpose
	* the user holds a bypass role

	That second clause is load-bearing and was missing until 2026-08-26. A plain
	``startswith(prefix)`` guard made the return series unreachable: the form
	pre-fills ``KSIN-.YY.-.####`` on every Sales Invoice, that starts with ``KS``,
	so the guard returned before the ``use_for_return`` branch ever ran and a
	credit note took the invoice counter. Blanking the field does not help either
	— ``Document.insert`` calls ``_set_defaults()`` and puts it straight back.
	"""
	if not doc.meta.has_field("naming_series"):
		return

	prefix, rows = _branch_series_rows(doc.doctype)
	if not rows:
		return

	current = doc.get("naming_series") or ""
	is_return = cint(doc.get("is_return"))

	match = next((r for r in rows if cint(r.use_for_return) == is_return), None)
	if not match:
		return
	if current == match.naming_series:
		return

	# The branch's series for the other return flavour is what the form pre-fills,
	# so it is never a deliberate choice on this document — the prefix guard must
	# not protect it.
	other = {r.naming_series for r in rows if cint(r.use_for_return) != is_return}
	if prefix and current.startswith(prefix) and current not in other:
		return

	doc.naming_series = match.naming_series
