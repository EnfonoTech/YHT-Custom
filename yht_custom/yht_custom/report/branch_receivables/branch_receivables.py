# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Branch Receivables — what each customer still owes, aged.

Outstanding is computed from `Payment Ledger Entry`, not from
`Sales Invoice.outstanding_amount`. The stored field only ever holds TODAY's
figure, so a report that read it while offering an "as on" date would answer a
question about March with September's number and look entirely plausible doing
it. The ledger sums to the same total for as-on-today and is genuinely
point-in-time for any earlier date.

`Branch User` already holds read on Payment Ledger Entry — granted in
`setup.BRANCH_USER_PERMISSIONS` for the Accounts Receivable Summary report, which
joins the same table.
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt, getdate, nowdate

from yht_custom import report_scope

#: Upper bound of each bucket in days past due; the last bucket is open-ended.
AGING_BUCKETS = (30, 60, 90)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	as_on = getdate(filters.get("as_on_date") or nowdate())

	outstanding = _outstanding_as_on(filters, as_on)
	if not outstanding:
		return _columns(), [], None, None

	rows = _rows(outstanding, filters, as_on)
	return _columns(), rows, None, _chart(rows)


# ------------------------------------------------------------------- the ledger


def _outstanding_as_on(filters, as_on):
	"""{invoice: outstanding} in company currency, as at ``as_on``."""
	ple = frappe.qb.DocType("Payment Ledger Entry")

	query = (
		frappe.qb.from_(ple)
		.select(ple.against_voucher_no.as_("invoice"), Sum(ple.amount).as_("outstanding"))
		.where(ple.delinked == 0)
		.where(ple.against_voucher_type == "Sales Invoice")
		.where(ple.party_type == "Customer")
		.where(ple.posting_date <= as_on)
		.groupby(ple.against_voucher_no)
		.having(Sum(ple.amount) != 0)
	)

	company = report_scope.company_filter(filters)
	if company:
		query = query.where(ple.company == company)
	if filters.get("customer"):
		query = query.where(ple.party == filters.get("customer"))

	return {row.invoice: flt(row.outstanding) for row in query.run(as_dict=True)}


# --------------------------------------------------------------------- rows


def _rows(outstanding, filters, as_on):
	si = frappe.qb.DocType("Sales Invoice")

	query = (
		frappe.qb.from_(si)
		.select(
			si.name,
			si.customer,
			si.customer_name,
			si.posting_date,
			si.due_date,
			si.base_rounded_total,
			si.base_grand_total,
			si.status,
		)
		.where(si.docstatus == 1)
		.where(si.name.isin(list(outstanding)))
	)

	scoped = _scope(query, si, filters)
	invoices = scoped.run(as_dict=True)

	only_overdue = cint(filters.get("only_overdue"))
	rows = []

	for invoice in invoices:
		balance = outstanding.get(invoice.name)
		if not balance:
			continue

		due = getdate(invoice.due_date or invoice.posting_date)
		days = (as_on - due).days
		if only_overdue and days <= 0:
			continue

		# base_rounded_total is 0 on an invoice with rounding disabled, so it can
		# never be trusted on its own — the same trap that left 0.50 unpaid on a
		# hand-built Payment Entry.
		total = flt(invoice.base_rounded_total) or flt(invoice.base_grand_total)

		row = {
			"customer": invoice.customer,
			"customer_name": invoice.customer_name,
			"invoice": invoice.name,
			"posting_date": invoice.posting_date,
			"due_date": invoice.due_date,
			"status": invoice.status,
			"grand_total": total,
			"paid": total - balance,
			"outstanding": balance,
			"days_overdue": max(days, 0),
		}
		row.update(_bucket(balance, days))
		rows.append(row)

	rows.sort(key=lambda r: (r["customer_name"] or "", r["posting_date"]))
	return rows


def _scope(query, si, filters):
	warehouses = report_scope.resolve_warehouses(filters.get("warehouse"))
	if not warehouses:
		return query

	sii = frappe.qb.DocType("Sales Invoice Item")
	in_warehouse = (
		frappe.qb.from_(sii).select(sii.parent).where(sii.warehouse.isin(warehouses))
	)

	scope = si.name.isin(in_warehouse) | si.set_warehouse.isin(warehouses)
	if report_scope.is_restricted():
		scope = scope | si.owner.isin(report_scope.allowed_owners())

	return query.where(scope)


def _bucket(balance, days):
	"""Place the balance in exactly one ageing column."""
	buckets = {name: 0.0 for name in _bucket_names()}
	names = _bucket_names()

	for index, limit in enumerate(AGING_BUCKETS):
		if days <= limit:
			buckets[names[index]] = balance
			return buckets

	buckets[names[-1]] = balance
	return buckets


def _bucket_names():
	names = []
	previous = 0
	for limit in AGING_BUCKETS:
		names.append(f"range_{previous}_{limit}")
		previous = limit + 1
	names.append(f"range_{AGING_BUCKETS[-1]}_above")
	return names


def _bucket_labels():
	labels = []
	previous = 0
	for limit in AGING_BUCKETS:
		labels.append(_("{0}-{1} Days").format(previous, limit))
		previous = limit + 1
	labels.append(_("{0}+ Days").format(AGING_BUCKETS[-1]))
	return labels


# ---------------------------------------------------------------- presentation


def _columns():
	money = {"fieldtype": "Currency", "options": "Company:company:default_currency"}

	columns = [
		{
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Link",
			"options": "Customer",
			"width": 150,
		},
		{"fieldname": "customer_name", "label": _("Customer Name"), "fieldtype": "Data", "width": 220},
		{
			"fieldname": "invoice",
			"label": _("Invoice"),
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 160,
		},
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "due_date", "label": _("Due Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "grand_total", "label": _("Invoice Total"), "width": 130, **money},
		{"fieldname": "paid", "label": _("Paid"), "width": 120, **money},
		{"fieldname": "outstanding", "label": _("Outstanding"), "width": 130, **money},
		{"fieldname": "days_overdue", "label": _("Days Overdue"), "fieldtype": "Int", "width": 110},
	]

	for fieldname, label in zip(_bucket_names(), _bucket_labels(), strict=True):
		columns.append({"fieldname": fieldname, "label": label, "width": 120, **money})

	columns.append({"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 110})
	return columns


def _chart(rows):
	"""Total per ageing bucket — the shape of the debt, not its line items."""
	if not rows:
		return None

	names = _bucket_names()
	totals = [sum(flt(row.get(name)) for row in rows) for name in names]

	return {
		"data": {
			"labels": _bucket_labels(),
			"datasets": [{"name": _("Outstanding"), "values": totals}],
		},
		"type": "bar",
		"fieldtype": "Currency",
	}
