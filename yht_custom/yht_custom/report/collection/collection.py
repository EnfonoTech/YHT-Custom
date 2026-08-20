# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Collection — money actually received from customers over a period.

Two sources, not one. Measured on this site:

    Payment Entry  (Receive / Customer, submitted)   783 rows   SAR 9,065,318.55
    Sales Invoice Payment (cash paid at the till)    562 rows

A collection report built on Payment Entry alone — the obvious first cut — would
miss every till receipt on the 518 POS invoices, and the branch's cash drawer
would never appear. Both are reported, tagged by source, and the source filter
lets an accountant isolate either.

The two do not double count each other: a till receipt is settled on the invoice
itself and raises no Payment Entry. Where a POS invoice somehow also carries a
Payment Entry, both lines show — deliberately, because that pairing is a data
defect worth seeing rather than silently netting away.
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, nowdate

from yht_custom import report_scope

SOURCE_PAYMENT_ENTRY = "Payment Entry"
SOURCE_INVOICE = "Invoice Payment"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	source = filters.get("source") or "All"

	rows = []
	if source in ("All", SOURCE_PAYMENT_ENTRY):
		rows += _payment_entries(filters)
	if source in ("All", SOURCE_INVOICE):
		rows += _invoice_payments(filters)

	rows.sort(key=lambda r: (r.get("posting_date"), r.get("voucher_no")))

	return _columns(), rows, None, _chart(rows)


# --------------------------------------------------------------- date window


def _window(filters):
	return (
		getdate(filters.get("from_date") or add_months(nowdate(), -1)),
		getdate(filters.get("to_date") or nowdate()),
	)


# ------------------------------------------------------------- payment entries


def _payment_entries(filters):
	pe = frappe.qb.DocType("Payment Entry")
	from_date, to_date = _window(filters)

	query = (
		frappe.qb.from_(pe)
		.select(
			pe.name,
			pe.posting_date,
			pe.party.as_("customer"),
			pe.party_name.as_("customer_name"),
			pe.mode_of_payment,
			pe.paid_to,
			pe.base_received_amount,
			pe.base_paid_amount,
			pe.reference_no,
		)
		.where(pe.docstatus == 1)
		.where(pe.payment_type == "Receive")
		.where(pe.party_type == "Customer")
		.where(pe.posting_date >= from_date)
		.where(pe.posting_date <= to_date)
	)

	company = report_scope.company_filter(filters)
	if company:
		query = query.where(pe.company == company)
	if filters.get("mode_of_payment"):
		query = query.where(pe.mode_of_payment == filters.get("mode_of_payment"))
	if filters.get("customer"):
		query = query.where(pe.party == filters.get("customer"))

	scoped_invoices = _invoices_in_scope(filters)
	if scoped_invoices is not None:
		# Mirrors branch_filters.payment_entry_query: the branch's own payments,
		# plus any payment settling an invoice the branch raised.
		per = frappe.qb.DocType("Payment Entry Reference")
		referencing = (
			frappe.qb.from_(per)
			.select(per.parent)
			.where(per.reference_doctype == "Sales Invoice")
			.where(per.reference_name.isin(scoped_invoices or [""]))
		)
		query = query.where(pe.owner.isin(report_scope.allowed_owners()) | pe.name.isin(referencing))

	entries = query.run(as_dict=True)
	if not entries:
		return []

	allocations = _allocations([entry.name for entry in entries])

	rows = []
	for entry in entries:
		rows.append(
			{
				"posting_date": entry.posting_date,
				"source": SOURCE_PAYMENT_ENTRY,
				"voucher_type": "Payment Entry",
				"voucher_no": entry.name,
				"customer": entry.customer,
				"customer_name": entry.customer_name,
				"mode_of_payment": entry.mode_of_payment,
				"account": entry.paid_to,
				"reference_no": entry.reference_no,
				"amount": flt(entry.base_received_amount) or flt(entry.base_paid_amount),
				"against_invoices": ", ".join(allocations.get(entry.name, [])),
			}
		)
	return rows


def _allocations(names):
	per = frappe.qb.DocType("Payment Entry Reference")
	rows = (
		frappe.qb.from_(per)
		.select(per.parent, per.reference_name)
		.where(per.parent.isin(names))
		.where(per.reference_doctype == "Sales Invoice")
		.run(as_dict=True)
	)
	out = {}
	for row in rows:
		out.setdefault(row.parent, []).append(row.reference_name)
	return out


# ------------------------------------------------------------ till collections


def _invoice_payments(filters):
	si = frappe.qb.DocType("Sales Invoice")
	sip = frappe.qb.DocType("Sales Invoice Payment")
	from_date, to_date = _window(filters)

	query = (
		frappe.qb.from_(sip)
		.inner_join(si)
		.on(sip.parent == si.name)
		.select(
			si.name,
			si.posting_date,
			si.customer,
			si.customer_name,
			sip.mode_of_payment,
			sip.account,
			sip.base_amount,
			sip.amount,
		)
		.where(si.docstatus == 1)
		.where(si.posting_date >= from_date)
		.where(si.posting_date <= to_date)
		.where(sip.amount != 0)
	)

	company = report_scope.company_filter(filters)
	if company:
		query = query.where(si.company == company)
	if filters.get("mode_of_payment"):
		query = query.where(sip.mode_of_payment == filters.get("mode_of_payment"))
	if filters.get("customer"):
		query = query.where(si.customer == filters.get("customer"))

	scoped_invoices = _invoices_in_scope(filters)
	if scoped_invoices is not None:
		query = query.where(si.name.isin(scoped_invoices or [""]))

	return [
		{
			"posting_date": row.posting_date,
			"source": SOURCE_INVOICE,
			"voucher_type": "Sales Invoice",
			"voucher_no": row.name,
			"customer": row.customer,
			"customer_name": row.customer_name,
			"mode_of_payment": row.mode_of_payment,
			"account": row.account,
			"reference_no": None,
			"amount": flt(row.base_amount) or flt(row.amount),
			"against_invoices": row.name,
		}
		for row in query.run(as_dict=True)
	]


# ------------------------------------------------------------------- scoping


def _invoices_in_scope(filters):
	"""Sales Invoices the caller may see, or ``None`` for no restriction.

	Resolved once and reused by both halves of the report so the two sources can
	never disagree about which invoices belong to the branch.
	"""
	warehouses = report_scope.resolve_warehouses(filters.get("warehouse"))
	if not warehouses:
		return None

	si = frappe.qb.DocType("Sales Invoice")
	sii = frappe.qb.DocType("Sales Invoice Item")

	scope = sii.warehouse.isin(warehouses) | si.set_warehouse.isin(warehouses)
	if report_scope.is_restricted():
		scope = scope | si.owner.isin(report_scope.allowed_owners())

	rows = (
		frappe.qb.from_(si)
		.left_join(sii)
		.on(sii.parent == si.name)
		.select(si.name)
		.distinct()
		.where(si.docstatus == 1)
		.where(scope)
		.run(pluck=True)
	)
	return rows


# ---------------------------------------------------------------- presentation


def _columns():
	return [
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "source", "label": _("Source"), "fieldtype": "Data", "width": 130},
		{"fieldname": "voucher_type", "label": _("Voucher Type"), "fieldtype": "Data", "width": 0, "hidden": 1},
		{
			"fieldname": "voucher_no",
			"label": _("Voucher"),
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 160,
		},
		{
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Link",
			"options": "Customer",
			"width": 150,
		},
		{"fieldname": "customer_name", "label": _("Customer Name"), "fieldtype": "Data", "width": 220},
		{
			"fieldname": "mode_of_payment",
			"label": _("Mode of Payment"),
			"fieldtype": "Link",
			"options": "Mode of Payment",
			"width": 160,
		},
		{
			"fieldname": "amount",
			"label": _("Amount"),
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 140,
		},
		{"fieldname": "reference_no", "label": _("Reference No"), "fieldtype": "Data", "width": 130},
		{"fieldname": "against_invoices", "label": _("Against Invoices"), "fieldtype": "Data", "width": 220},
		{"fieldname": "account", "label": _("Account"), "fieldtype": "Link", "options": "Account", "width": 180},
	]


def _chart(rows):
	"""Collected per mode of payment — the question a branch actually asks."""
	if not rows:
		return None

	totals = {}
	for row in rows:
		mode = row.get("mode_of_payment") or _("Unspecified")
		totals[mode] = totals.get(mode, 0.0) + flt(row.get("amount"))

	ordered = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:10]

	return {
		"data": {
			"labels": [mode for mode, _total in ordered],
			"datasets": [{"name": _("Collected"), "values": [total for _mode, total in ordered]}],
		},
		"type": "bar",
		"fieldtype": "Currency",
	}
