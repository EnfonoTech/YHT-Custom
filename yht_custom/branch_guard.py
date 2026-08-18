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

#: Header field -> label, per doctype. Item-row fields are handled generically.
HEADER_WAREHOUSE_FIELDS = ("set_warehouse", "set_from_warehouse", "from_warehouse", "to_warehouse")
ITEM_WAREHOUSE_FIELDS = ("warehouse", "target_warehouse", "s_warehouse", "t_warehouse", "from_warehouse")


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


def validate_branch_scope(doc, method=None):
	"""Reject warehouses and cost centers outside the user's branch."""
	if _is_bypass():
		return

	warehouses, cost_centers = _branch_scope()
	if warehouses is None:
		return  # not a branch-mapped user

	offences = []

	# --- header warehouse fields ---
	for fieldname in HEADER_WAREHOUSE_FIELDS:
		if not doc.meta.has_field(fieldname):
			continue
		value = doc.get(fieldname)
		if value and warehouses and value not in warehouses:
			offences.append((_("Warehouse"), doc.meta.get_label(fieldname), value))

	# --- header cost center ---
	if doc.meta.has_field("cost_center") and cost_centers:
		value = doc.get("cost_center")
		if value and value not in cost_centers:
			offences.append((_("Cost Center"), doc.meta.get_label("cost_center"), value))

	# --- item rows ---
	for row in doc.get("items") or []:
		for fieldname in ITEM_WAREHOUSE_FIELDS:
			if not row.meta.has_field(fieldname):
				continue
			value = row.get(fieldname)
			if value and warehouses and value not in warehouses:
				offences.append((_("Warehouse"), f"{_('Row')} {row.idx} {row.meta.get_label(fieldname)}", value))

		if row.meta.has_field("cost_center") and cost_centers:
			value = row.get("cost_center")
			if value and value not in cost_centers:
				offences.append(
					(_("Cost Center"), f"{_('Row')} {row.idx} {row.meta.get_label('cost_center')}", value)
				)

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
