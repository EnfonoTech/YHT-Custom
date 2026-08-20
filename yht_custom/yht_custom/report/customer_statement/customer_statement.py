# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Customer Statement — MoM §2.6, one of the eight named reports.

The branch dashboard has advertised a "Customer Statement" tile since it was
built, and it opened **General Ledger**. An operator following the written guide
landed on a screen with a different name, different filters and every party in the
company on it. This is the report the tile was always supposed to open.

Built on GL Entry against the customer's receivable account, not on Sales Invoice.
An invoice-based statement misses journal entries, write-offs and on-account
payments — 59 of this sample customer's 4,412 ledger rows come from vouchers that
are not invoices, and a statement a customer can dispute is worse than none.

SCOPE, STATED PLAINLY. A statement is a CUSTOMER-level document: it has to foot to
the customer's actual balance or it is not a statement. So a branch user is gated
on whether they may see this customer at all — they must have transacted with them
— and then sees the complete ledger. Showing a branch-filtered subset would
produce a "balance" that reconciles against nothing and that the customer would
reject. On this single-branch site the distinction is moot; it is written down
because it stops being moot the day branch two arrives.
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, nowdate

from yht_custom import report_scope


def execute(filters=None):
	filters = frappe._dict(filters or {})
	customer = filters.get("customer")
	if not customer:
		frappe.throw(_("Select a customer"))

	_check_access(customer)

	from_date = getdate(filters.get("from_date") or add_months(nowdate(), -12))
	to_date = getdate(filters.get("to_date") or nowdate())
	company = report_scope.company_filter(filters)

	opening = _opening(customer, company, from_date)
	entries = _entries(customer, company, from_date, to_date)

	rows, balance = _with_running_balance(opening, entries, from_date)
	return _columns(), rows, None, None, _summary(opening, entries, balance)


def _check_access(customer):
	"""A branch user may only pull a statement for a customer they deal with.

	Deliberately NOT a warehouse filter on the rows — see the module docstring.
	"""
	if not report_scope.is_restricted():
		return

	warehouses = report_scope.allowed_warehouses()
	if not warehouses:
		return

	si = frappe.qb.DocType("Sales Invoice")
	sii = frappe.qb.DocType("Sales Invoice Item")
	exists = (
		frappe.qb.from_(si)
		.left_join(sii)
		.on(sii.parent == si.name)
		.select(si.name)
		.where(si.customer == customer)
		.where(si.docstatus == 1)
		.where(
			sii.warehouse.isin(warehouses)
			| si.set_warehouse.isin(warehouses)
			| si.owner.isin(report_scope.allowed_owners())
		)
		.limit(1)
		.run()
	)
	if not exists:
		frappe.throw(
			_("{0} has no transactions in your branch.").format(frappe.bold(customer)),
			title=_("Outside your branch"),
		)


def _receivable_filter(query, gl, customer, company):
	query = (
		query.where(gl.is_cancelled == 0)
		.where(gl.party_type == "Customer")
		.where(gl.party == customer)
	)
	if company:
		query = query.where(gl.company == company)
	return query


def _opening(customer, company, from_date):
	gl = frappe.qb.DocType("GL Entry")
	from frappe.query_builder.functions import Sum

	query = _receivable_filter(
		frappe.qb.from_(gl).select(
			Sum(gl.debit).as_("debit"), Sum(gl.credit).as_("credit")
		),
		gl,
		customer,
		company,
	).where(gl.posting_date < from_date)

	row = query.run(as_dict=True)[0]
	return flt(row.debit) - flt(row.credit)


def _entries(customer, company, from_date, to_date):
	gl = frappe.qb.DocType("GL Entry")
	query = _receivable_filter(
		frappe.qb.from_(gl).select(
			gl.posting_date,
			gl.voucher_type,
			gl.voucher_no,
			gl.account,
			gl.remarks,
			gl.against_voucher,
			gl.debit,
			gl.credit,
		),
		gl,
		customer,
		company,
	)
	return (
		query.where(gl.posting_date >= from_date)
		.where(gl.posting_date <= to_date)
		.orderby(gl.posting_date)
		.orderby(gl.creation)
		.run(as_dict=True)
	)


def _with_running_balance(opening, entries, from_date):
	rows = [
		{
			"posting_date": from_date,
			"voucher_type": "",
			"voucher_no": "",
			"particulars": _("Opening Balance"),
			"debit": opening if opening > 0 else 0,
			"credit": -opening if opening < 0 else 0,
			"balance": opening,
			"is_total": 1,
		}
	]

	balance = opening
	for entry in entries:
		balance += flt(entry.debit) - flt(entry.credit)
		rows.append(
			{
				"posting_date": entry.posting_date,
				"voucher_type": entry.voucher_type,
				"voucher_no": entry.voucher_no,
				"particulars": _particulars(entry),
				"debit": flt(entry.debit),
				"credit": flt(entry.credit),
				"balance": balance,
			}
		)

	rows.append(
		{
			"posting_date": rows[-1]["posting_date"],
			"voucher_type": "",
			"voucher_no": "",
			"particulars": _("Closing Balance"),
			"debit": sum(flt(e.debit) for e in entries),
			"credit": sum(flt(e.credit) for e in entries),
			"balance": balance,
			"is_total": 1,
		}
	)
	return rows, balance


def _particulars(entry):
	"""What the line is FOR, in the order a reader would want it."""
	if entry.against_voucher and entry.against_voucher != entry.voucher_no:
		return _("Against {0}").format(entry.against_voucher)
	remarks = (entry.remarks or "").strip()
	if remarks and remarks.lower() != "no remarks":
		return remarks[:180]
	return entry.voucher_type or ""


def _columns():
	money = {"fieldtype": "Currency", "options": "Company:company:default_currency"}
	return [
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "voucher_type", "label": _("Type"), "fieldtype": "Data", "width": 0, "hidden": 1},
		{
			"fieldname": "voucher_no",
			"label": _("Voucher"),
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 170,
		},
		{"fieldname": "particulars", "label": _("Particulars"), "fieldtype": "Data", "width": 330},
		{"fieldname": "debit", "label": _("Debit"), "width": 130, **money},
		{"fieldname": "credit", "label": _("Credit"), "width": 130, **money},
		{"fieldname": "balance", "label": _("Balance"), "width": 140, **money},
	]


def _summary(opening, entries, closing):
	debit = sum(flt(e.debit) for e in entries)
	credit = sum(flt(e.credit) for e in entries)
	return [
		{"label": _("Opening"), "value": opening, "datatype": "Currency"},
		{"label": _("Invoiced"), "value": debit, "datatype": "Currency"},
		{"label": _("Received"), "value": credit, "datatype": "Currency"},
		{
			"label": _("Closing"),
			"value": closing,
			"datatype": "Currency",
			"indicator": "Red" if closing > 0 else "Green",
		},
	]
