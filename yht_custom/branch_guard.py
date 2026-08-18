# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Server-side branch scope enforcement.

This is the boundary that makes `setup_property_setters` safe. Those Property
Setters switch off Frappe's link-level User Permission check on warehouse and
cost-center fields — necessary, or branch users cannot open documents at all —
and **this module is what replaces it**.

It runs on `validate`, so it catches every write path: the desk form, a REST
call to `frappe.client.save`, a bulk import, a Server Script. Client-side
`set_query` filters shape the pickers but enforce nothing; this does.

No-ops for anyone not listed on a Branch Configuration, and for the bypass roles
that legitimately work across branches.
"""

import frappe
from frappe import _

from yht_custom.branch_defaults import BYPASS_ROLES, _is_bypass, _user_branch_config

from yht_custom.branch_fields import GUARD_EXCLUDE, GUARDED_PARENTS, get_scoped_fields


def _branch_scope(user=None):
	"""(warehouses, cost_centers) the user may post to, or (None, None) for no limit."""
	config = _user_branch_config(user)
	if not config:
		return None, None

	warehouses = set(
		frappe.get_all("Branch Configuration Warehouse", filters={"parent": config}, pluck="warehouse")
	)
	cost_centers = set(
		frappe.get_all("Branch Configuration Cost Center", filters={"parent": config}, pluck="cost_center")
	)
	# The company default cost center is granted alongside the branch's own,
	# because ERPNext tax templates hardcode it — mirror that here or every
	# tax-bearing document fails the guard.
	company = frappe.db.get_value("Branch Configuration", config, "company")
	if company:
		default_cc = frappe.db.get_value("Company", company, "cost_center")
		if default_cc:
			cost_centers.add(default_cc)

	return warehouses, cost_centers


ALLOWED_BY_TARGET = {"Warehouse": 0, "Cost Center": 1}


def _check(doc_or_row, doctype, allowed, prefix=""):
	"""Collect scope offences on one document or child row.

	Fields come from live metadata, so a field ERPNext adds in a later version is
	guarded automatically instead of silently escaping the check.
	"""
	offences = []
	fields = get_scoped_fields(doctype)

	for target, permitted in (("Warehouse", allowed[0]), ("Cost Center", allowed[1])):
		if not permitted:
			continue
		for fieldname in fields[target]:
			if (doctype, fieldname) in GUARD_EXCLUDE:
				continue
			value = doc_or_row.get(fieldname)
			if value and value not in permitted:
				label = doc_or_row.meta.get_label(fieldname) if doc_or_row.meta.get_field(fieldname) else fieldname
				offences.append((_(target), f"{prefix}{label}", value))
	return offences


def validate_branch_scope(doc, method=None):
	"""Reject warehouses and cost centers outside the user's branch."""
	if _is_bypass():
		return

	warehouses, cost_centers = _branch_scope()
	if warehouses is None:
		return  # not a branch-mapped user

	allowed = (warehouses, cost_centers)
	offences = _check(doc, doc.doctype, allowed)

	child_field = GUARDED_PARENTS.get(doc.doctype, "items")
	if child_field:
		for row in doc.get(child_field) or []:
			offences += _check(row, row.doctype, allowed, prefix=f"{_('Row')} {row.idx} ")

	if not offences:
		return

	lines = "".join(f"<li>{kind} — {where}: <b>{frappe.utils.escape_html(value)}</b></li>" for kind, where, value in offences)
	frappe.throw(
		_("These values belong to another branch and cannot be used here:")
		+ f"<ul>{lines}</ul>"
		+ _("Ask a Stock Manager if you need to transact across branches."),
		title=_("Outside Your Branch"),
	)


# ----------------------------------------------------------------- form filters


@frappe.whitelist()
def get_branch_scope() -> dict:
	"""Warehouses and cost centers for the current user — powers form filters.

	Returns empty lists for unrestricted users, which the client reads as
	"apply no filter".
	"""
	if _is_bypass():
		return {"restricted": False, "warehouses": [], "cost_centers": []}

	warehouses, cost_centers = _branch_scope()
	if warehouses is None:
		return {"restricted": False, "warehouses": [], "cost_centers": []}

	return {
		"restricted": True,
		"warehouses": sorted(warehouses),
		"cost_centers": sorted(cost_centers),
	}
