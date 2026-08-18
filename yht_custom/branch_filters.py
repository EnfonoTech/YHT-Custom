# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Branch-scoped list filtering.

Registered as ``permission_query_conditions``. Each function returns a SQL WHERE
fragment, so values must be escaped by hand — Frappe gives no parameter binding
at this hook. ``frappe.db.escape`` is the correct tool and is used throughout;
nothing here is ever built from an f-string over raw user input.

Source of truth for "which branch is this user in" is the ``Branch Configuration
User`` table, deliberately NOT roles and NOT User Permissions:

* roles lag — a user can be listed on a branch before the role lands
* User Permissions are an *output* of Branch Configuration, so reading them here
  would make the filter depend on its own side effect
"""

import frappe

BYPASS_ROLES = ("System Manager", "Stock Manager")


def get_branch_warehouses(user: str | None = None) -> list[str]:
	"""Warehouses the user may see, or ``[]`` for no restriction.

	An empty list means "do not filter" — either the user is an admin, or they
	are not on any Branch Configuration at all and standard Frappe permissions
	already govern them.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return []

	if set(frappe.get_roles(user)) & set(BYPASS_ROLES):
		return []

	configs = frappe.get_all("Branch Configuration User", filters={"user": user}, pluck="parent")
	if not configs:
		return []

	warehouses = frappe.get_all(
		"Branch Configuration Warehouse", filters={"parent": ["in", configs]}, pluck="warehouse"
	)
	return sorted({w for w in warehouses if w})


def _escaped_list(values) -> str:
	return ", ".join(frappe.db.escape(v) for v in values)


#: MoM 2.5 — "Cancelled documents hidden from branch users". Appended to every
#: branch filter rather than bolted on per doctype.
def _hide_cancelled(doctype: str) -> str:
	return f"`tab{doctype}`.`docstatus` != 2"


def _warehouse_or_owner(doctype: str, header_fields: list[str], item_doctype: str | None, user: str) -> str:
	"""Standard shape: header warehouse matches, an item row matches, or own doc.

	Owner is always included so a user never loses sight of something they
	created — e.g. a draft raised before their warehouse mapping was finished.
	"""
	warehouses = get_branch_warehouses(user)
	if not warehouses:
		return ""

	wh = _escaped_list(warehouses)
	safe_user = frappe.db.escape(user)
	clauses = [f"`tab{doctype}`.`{f}` IN ({wh})" for f in header_fields]

	if item_doctype:
		clauses.append(
			f"`tab{doctype}`.`name` IN ("
			f"SELECT DISTINCT `parent` FROM `tab{item_doctype}` WHERE `warehouse` IN ({wh}))"
		)

	clauses.append(f"`tab{doctype}`.`owner` = {safe_user}")
	scope = "(" + " OR ".join(clauses) + ")"
	return f"{scope} AND {_hide_cancelled(doctype)}"


def _owner_only(doctype: str, user: str) -> str:
	"""For doctypes with no warehouse of their own."""
	if not user or user == "Administrator":
		return ""
	if set(frappe.get_roles(user)) & set(BYPASS_ROLES):
		return ""
	if not frappe.db.exists("Branch Configuration User", {"user": user}):
		return ""
	return f"`tab{doctype}`.`owner` = {frappe.db.escape(user)} AND {_hide_cancelled(doctype)}"


# --------------------------------------------------------------- per-doctype


def sales_invoice_query(user):
	return _warehouse_or_owner("Sales Invoice", ["set_warehouse"], "Sales Invoice Item", user)


def purchase_invoice_query(user):
	return _warehouse_or_owner("Purchase Invoice", ["set_warehouse"], "Purchase Invoice Item", user)


def delivery_note_query(user):
	return _warehouse_or_owner("Delivery Note", ["set_warehouse"], "Delivery Note Item", user)


def purchase_receipt_query(user):
	return _warehouse_or_owner("Purchase Receipt", ["set_warehouse"], "Purchase Receipt Item", user)


def sales_order_query(user):
	return _warehouse_or_owner("Sales Order", ["set_warehouse"], "Sales Order Item", user)


def material_request_query(user):
	return _warehouse_or_owner(
		"Material Request", ["set_warehouse", "set_from_warehouse"], "Material Request Item", user
	)


def stock_entry_query(user):
	"""Stock Entry keeps its warehouses on the child rows under different names.

	Without this filter a Branch User holding read on Stock Entry would see every
	branch's movements in the list view.
	"""
	warehouses = get_branch_warehouses(user)
	if not warehouses:
		return ""
	wh = _escaped_list(warehouses)
	return (
		"(`tabStock Entry`.`from_warehouse` IN ({wh})"
		" OR `tabStock Entry`.`to_warehouse` IN ({wh})"
		" OR `tabStock Entry`.`name` IN ("
		"SELECT DISTINCT `parent` FROM `tabStock Entry Detail`"
		" WHERE `s_warehouse` IN ({wh}) OR `t_warehouse` IN ({wh}))"
		" OR `tabStock Entry`.`owner` = {user})"
		" AND `tabStock Entry`.`docstatus` != 2"
	).format(wh=wh, user=frappe.db.escape(user))


def quotation_query(user):
	"""Quotations carry no warehouse worth filtering on — scope to own records."""
	return _owner_only("Quotation", user)


def payment_entry_query(user):
	"""Own payments, plus any settling an invoice from the user's warehouses."""
	if not user or user == "Administrator":
		return ""
	if set(frappe.get_roles(user)) & set(BYPASS_ROLES):
		return ""
	if not frappe.db.exists("Branch Configuration User", {"user": user}):
		return ""

	safe_user = frappe.db.escape(user)
	warehouses = get_branch_warehouses(user)
	if not warehouses:
		return f"`tabPayment Entry`.`owner` = {safe_user} AND `tabPayment Entry`.`docstatus` != 2"

	wh = _escaped_list(warehouses)
	return (
		"(`tabPayment Entry`.`owner` = {user}"
		" OR `tabPayment Entry`.`name` IN ("
		"SELECT DISTINCT per.`parent` FROM `tabPayment Entry Reference` per"
		" INNER JOIN `tabSales Invoice Item` sii ON sii.`parent` = per.`reference_name`"
		" WHERE per.`reference_doctype` = 'Sales Invoice' AND sii.`warehouse` IN ({wh})))"
		" AND `tabPayment Entry`.`docstatus` != 2"
	).format(user=safe_user, wh=wh)
