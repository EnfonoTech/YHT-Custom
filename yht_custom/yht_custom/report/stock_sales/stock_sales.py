# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Stock Sales — what was sold, by item, item group or customer.

MoM §2.6 names this report but does not specify it, so the shape is the one the
branch actually asks for: quantity and value out of a warehouse over a period,
grouped three ways off one query.

Returns are NOT excluded. A credit note carries negative qty and negative amount
on its rows, so summing them nets the period down — which is what "what did we
sell" means to an accountant. 99 of this site's 2,344 submitted invoices are
returns; dropping them would overstate every line.
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Count, Sum
from frappe.utils import add_months, flt, getdate, nowdate

from yht_custom import report_scope

#: Dimension → (fieldname, label, fieldtype, options) for the leading column(s).
GROUP_BY_CHOICES = ("Item", "Item Group", "Customer")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	group_by = filters.get("group_by") or "Item"
	if group_by not in GROUP_BY_CHOICES:
		frappe.throw(_("Unknown grouping"))

	rows = _fetch(filters, group_by)
	columns = _columns(group_by)
	return columns, rows, None, _chart(rows, group_by)


# ------------------------------------------------------------------ the query


def _fetch(filters, group_by):
	si = frappe.qb.DocType("Sales Invoice")
	sii = frappe.qb.DocType("Sales Invoice Item")

	from_date = getdate(filters.get("from_date") or add_months(nowdate(), -1))
	to_date = getdate(filters.get("to_date") or nowdate())

	query = (
		frappe.qb.from_(sii)
		.inner_join(si)
		.on(sii.parent == si.name)
		.where(si.docstatus == 1)
		.where(si.posting_date >= from_date)
		.where(si.posting_date <= to_date)
	)

	company = report_scope.company_filter(filters)
	if company:
		query = query.where(si.company == company)

	query = _apply_scope(query, si, sii, filters)

	if filters.get("item_group"):
		query = query.where(sii.item_group == filters.get("item_group"))
	if filters.get("customer"):
		query = query.where(si.customer == filters.get("customer"))
	if filters.get("item_code"):
		query = query.where(sii.item_code == filters.get("item_code"))

	qty = Sum(sii.stock_qty).as_("qty")
	amount = Sum(sii.base_net_amount).as_("amount")
	# Count(field).distinct(), not Count(field.distinct()) — a pypika Field has no
	# .distinct(); the DISTINCT belongs to the aggregate function.
	invoices = Count(si.name).distinct().as_("invoices")

	if group_by == "Item":
		query = query.select(
			sii.item_code,
			sii.item_name,
			sii.item_group,
			sii.stock_uom.as_("uom"),
			qty,
			amount,
			invoices,
		).groupby(sii.item_code, sii.item_name, sii.item_group, sii.stock_uom)
	elif group_by == "Item Group":
		query = query.select(sii.item_group, qty, amount, invoices).groupby(sii.item_group)
	else:
		query = query.select(si.customer, si.customer_name, qty, amount, invoices).groupby(
			si.customer, si.customer_name
		)

	rows = query.orderby(Sum(sii.base_net_amount), order=frappe.qb.desc).run(as_dict=True)

	for row in rows:
		# Average realised rate, not the list rate — a discounted line should read
		# as what it actually fetched.
		row["avg_rate"] = flt(row.amount) / flt(row.qty) if flt(row.qty) else 0.0

	return rows


def _apply_scope(query, si, sii, filters):
	"""Restrict to the branch, mirroring `branch_filters` exactly.

	The owner arm is not decoration: 143 Sales Invoice Item rows on this site carry
	a blank `warehouse`, and a warehouse-only filter would drop them from the
	branch's own report while the list view still showed the invoice.
	"""
	warehouses = report_scope.resolve_warehouses(filters.get("warehouse"))
	if not warehouses:
		return query

	scope = sii.warehouse.isin(warehouses)

	if report_scope.is_restricted():
		blank = (sii.warehouse.isnull()) | (sii.warehouse == "")
		scope = (
			scope
			| (blank & si.set_warehouse.isin(warehouses))
			| si.owner.isin(report_scope.allowed_owners())
		)

	return query.where(scope)


# ---------------------------------------------------------------- presentation


def _columns(group_by):
	money = {"fieldtype": "Currency", "options": "Company:company:default_currency"}

	if group_by == "Item":
		leading = [
			{"fieldname": "item_code", "label": _("Item Code"), "fieldtype": "Link", "options": "Item", "width": 170},
			{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 220},
			{
				"fieldname": "item_group",
				"label": _("Item Group"),
				"fieldtype": "Link",
				"options": "Item Group",
				"width": 150,
			},
			{"fieldname": "uom", "label": _("UOM"), "fieldtype": "Data", "width": 70},
		]
	elif group_by == "Item Group":
		leading = [
			{
				"fieldname": "item_group",
				"label": _("Item Group"),
				"fieldtype": "Link",
				"options": "Item Group",
				"width": 260,
			}
		]
	else:
		leading = [
			{
				"fieldname": "customer",
				"label": _("Customer"),
				"fieldtype": "Link",
				"options": "Customer",
				"width": 170,
			},
			{"fieldname": "customer_name", "label": _("Customer Name"), "fieldtype": "Data", "width": 240},
		]

	return leading + [
		{"fieldname": "qty", "label": _("Qty Sold"), "fieldtype": "Float", "width": 110},
		{"fieldname": "amount", "label": _("Net Amount"), "width": 140, **money},
		{"fieldname": "avg_rate", "label": _("Avg Rate"), "width": 120, **money},
		{"fieldname": "invoices", "label": _("Invoices"), "fieldtype": "Int", "width": 90},
	]


def _chart(rows, group_by):
	"""Top ten by value. Anything more is unreadable at this width."""
	if not rows:
		return None

	label_field = {"Item": "item_code", "Item Group": "item_group", "Customer": "customer"}[group_by]
	top = rows[:10]

	return {
		"data": {
			"labels": [row.get(label_field) for row in top],
			"datasets": [{"name": _("Net Amount"), "values": [flt(row.get("amount")) for row in top]}],
		},
		"type": "bar",
		"fieldtype": "Currency",
	}
