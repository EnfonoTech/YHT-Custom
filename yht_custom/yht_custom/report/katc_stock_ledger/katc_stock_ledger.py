# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""KATC Stock Ledger — client sheet item 7.

The client asked for these columns, in these words:

    Date, voucher number, item code with item name, qty in, qty out,
    balance qty, transaction rate, valuation rate, balance value

ERPNext's own Stock Ledger answers a different question: it prints one signed
`actual_qty` column, plus in/out rate, plus a dozen columns nobody here reads.
Splitting the movement into IN and OUT is the whole point of the request — a
storekeeper reading a column of `-22.0` has to do sign arithmetic in their head
to answer "what left the store".

WHY IT IS A SCRIPT REPORT AND NOT A QUERY REPORT. `permission_query_conditions`
does NOT reach a report (gotcha 20), so an unscoped report shows a branch user
every branch's movements. Every report in this app resolves its branch through
`report_scope`, which reads the same helpers the list views do.

QTY IN / QTY OUT ARE DERIVED, NOT STORED. `Stock Ledger Entry.actual_qty` is a
single signed number: positive is a receipt, negative is an issue. A Stock
Reconciliation posts `actual_qty = 0` and moves `qty_after_transaction`
absolutely — 3,469 rows on this site do exactly that (gotcha 30) — so a
reconciliation shows zero in and zero out while the balance still steps. That is
correct and deliberate: nothing moved, the count was corrected.

TRANSACTION RATE IS NOT VALUATION RATE. `incoming_rate` is what this movement was
booked at and is 0 on an issue, because an issue is valued at the running
average. So the transaction-rate column falls back to the valuation rate on
outward rows rather than printing a misleading zero.
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, nowdate

from yht_custom import report_scope


def execute(filters=None):
	filters = frappe._dict(filters or {})

	from_date = getdate(filters.get("from_date") or add_months(nowdate(), -3))
	to_date = getdate(filters.get("to_date") or nowdate())
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	rows = _entries(filters, from_date, to_date)
	return _columns(), rows


def _columns():
	return [
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
		{
			"label": _("Voucher No"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link",
			"options": "voucher_type", "width": 150,
		},
		{"label": _("Voucher Type"), "fieldname": "voucher_type", "fieldtype": "Data", "width": 130},
		{
			"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link",
			"options": "Item", "width": 150,
		},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 220},
		{"label": _("Qty In"), "fieldname": "qty_in", "fieldtype": "Float", "width": 90},
		{"label": _("Qty Out"), "fieldname": "qty_out", "fieldtype": "Float", "width": 90},
		{"label": _("Balance Qty"), "fieldname": "balance_qty", "fieldtype": "Float", "width": 105},
		{"label": _("UOM"), "fieldname": "stock_uom", "fieldtype": "Data", "width": 70},
		{
			"label": _("Transaction Rate"), "fieldname": "transaction_rate",
			"fieldtype": "Currency", "width": 130,
		},
		{
			"label": _("Valuation Rate"), "fieldname": "valuation_rate",
			"fieldtype": "Currency", "width": 120,
		},
		{
			"label": _("Balance Value"), "fieldname": "balance_value",
			"fieldtype": "Currency", "width": 130,
		},
		{
			"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link",
			"options": "Warehouse", "width": 160,
		},
	]


def _entries(filters, from_date, to_date):
	where = [
		"sle.is_cancelled = 0",
		"sle.posting_date BETWEEN %(from_date)s AND %(to_date)s",
	]
	params = {"from_date": from_date, "to_date": to_date}

	company = report_scope.company_filter(filters)
	if company:
		where.append("sle.company = %(company)s")
		params["company"] = company

	if filters.get("item_code"):
		where.append("sle.item_code = %(item_code)s")
		params["item_code"] = filters.get("item_code")

	# Branch scope. `resolve_warehouses` expands a group and refuses one the caller
	# may not see, so a branch user cannot widen this by typing a warehouse in.
	warehouses = report_scope.resolve_warehouses(filters.get("warehouse"))
	if warehouses:
		where.append("sle.warehouse IN %(warehouses)s")
		params["warehouses"] = warehouses

	rows = frappe.db.sql(
		f"""
		SELECT sle.posting_date, sle.posting_time, sle.voucher_type, sle.voucher_no,
		       sle.item_code, sle.warehouse, sle.stock_uom,
		       sle.actual_qty, sle.qty_after_transaction,
		       sle.incoming_rate, sle.valuation_rate, sle.stock_value,
		       it.item_name
		FROM `tabStock Ledger Entry` sle
		LEFT JOIN `tabItem` it ON it.name = sle.item_code
		WHERE {' AND '.join(where)}
		ORDER BY sle.posting_date, sle.posting_time, sle.creation
		""",
		params,
		as_dict=True,
	)

	for row in rows:
		qty = flt(row.actual_qty)
		row["qty_in"] = qty if qty > 0 else 0
		row["qty_out"] = -qty if qty < 0 else 0
		row["balance_qty"] = flt(row.qty_after_transaction)
		row["balance_value"] = flt(row.stock_value)
		# `incoming_rate` is 0 on an issue — the movement is valued at the running
		# average — so printing it bare would read as "sold at zero".
		row["transaction_rate"] = flt(row.incoming_rate) or flt(row.valuation_rate)

	return rows
