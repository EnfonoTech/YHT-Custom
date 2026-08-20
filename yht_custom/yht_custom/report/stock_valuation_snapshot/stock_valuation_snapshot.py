# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Per-item, per-warehouse qty + valuation rate + value — the MoM deliverable.

The pre/post migration report the MoM names as the acceptance test. The ledger
columns sit beside the Bin columns so a reader can see at a glance whether the two
agree; a `Δ` on either is the signature of a broken import.

Not branch-scoped, deliberately. This is a finance and migration instrument, and
its roles are System Manager / Accounts Manager / Stock Manager — a branch user has
the Stock Balance report for their own warehouse.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from yht_custom import import_gate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	rows = [row for row in import_gate.snapshot() if _keep(row, filters)]

	for row in rows:
		row["qty_delta"] = flt(row.get("actual_qty")) - flt(row.get("ledger_qty"))
		row["value_delta"] = flt(row.get("stock_value")) - flt(row.get("ledger_value"))

	return _columns(), rows, None, None, _summary(rows)


def _keep(row, filters):
	if filters.get("warehouse") and row.get("warehouse") != filters.get("warehouse"):
		return False
	if filters.get("item_group") and row.get("item_group") != filters.get("item_group"):
		return False
	if filters.get("item_code") and row.get("item_code") != filters.get("item_code"):
		return False
	if cint(filters.get("only_problems")):
		# The three shapes §2.4 named, plus any Bin/ledger disagreement.
		return (
			flt(row.get("actual_qty")) < 0
			or flt(row.get("stock_value")) < 0
			or (flt(row.get("actual_qty")) > 0 and not flt(row.get("valuation_rate")))
			or abs(flt(row.get("actual_qty")) - flt(row.get("ledger_qty"))) > 0.001
			or abs(flt(row.get("stock_value")) - flt(row.get("ledger_value"))) > 0.05
		)
	return True


def _columns():
	money = {"fieldtype": "Currency", "options": "Company:company:default_currency"}
	return [
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 170},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 220},
		{
			"fieldname": "item_group",
			"label": _("Item Group"),
			"fieldtype": "Link",
			"options": "Item Group",
			"width": 150,
		},
		{
			"fieldname": "warehouse",
			"label": _("Warehouse"),
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 170,
		},
		{"fieldname": "actual_qty", "label": _("Qty"), "fieldtype": "Float", "width": 100},
		{"fieldname": "valuation_rate", "label": _("Valuation Rate"), "width": 130, **money},
		{"fieldname": "stock_value", "label": _("Stock Value"), "width": 130, **money},
		{"fieldname": "ledger_qty", "label": _("Ledger Qty"), "fieldtype": "Float", "width": 110},
		{"fieldname": "qty_delta", "label": _("Qty Δ"), "fieldtype": "Float", "width": 90},
		{"fieldname": "ledger_value", "label": _("Ledger Value"), "width": 130, **money},
		{"fieldname": "value_delta", "label": _("Value Δ"), "width": 110, **money},
		{"fieldname": "ledger_date", "label": _("Last Movement"), "fieldtype": "Date", "width": 110},
	]


def _summary(rows):
	negative = sum(1 for row in rows if flt(row.get("actual_qty")) < 0)
	zero_value = sum(
		1 for row in rows if flt(row.get("actual_qty")) > 0 and not flt(row.get("valuation_rate"))
	)
	disagree = sum(
		1
		for row in rows
		if abs(flt(row.get("qty_delta"))) > 0.001 or abs(flt(row.get("value_delta"))) > 0.05
	)
	return [
		{
			"label": _("Total Stock Value"),
			"value": sum(flt(row.get("stock_value")) for row in rows),
			"datatype": "Currency",
		},
		{
			"label": _("Negative Bins"),
			"value": negative,
			"datatype": "Int",
			"indicator": "Red" if negative else "Green",
		},
		{
			"label": _("Qty at Zero Value"),
			"value": zero_value,
			"datatype": "Int",
			"indicator": "Orange" if zero_value else "Green",
		},
		{
			"label": _("Disagree With Ledger"),
			"value": disagree,
			"datatype": "Int",
			"indicator": "Red" if disagree else "Green",
		},
	]
