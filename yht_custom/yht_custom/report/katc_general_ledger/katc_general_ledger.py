# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""KATC General Ledger — client sheet item 8.

The client asked for exactly six columns:

    Date, voucher number, Remarks, Debit, Credit, Balance

ERPNext's General Ledger prints eighteen and opens on a filter set that makes an
operator choose before they see anything. This is the same data, in the six
columns they named, with a running balance.

THE OPENING ROW IS NOT DECORATION. A ledger that starts at zero on the from-date
is wrong for every account that had a balance before it. The opening balance is
computed from everything before `from_date` and printed as the first row, so the
closing figure on screen is the account's real balance and not a period movement
pretending to be one.

BALANCE DIRECTION FOLLOWS THE ACCOUNT'S ROOT TYPE. Debit minus credit is right
for an asset or an expense and backwards for a liability, income or equity — a
payable would show its balance negative all year. `root_type` decides the sign,
so the number reads the way an accountant expects for that account.

SCOPE. `permission_query_conditions` does not reach a report (gotcha 20), so this
resolves its own. A GL Entry carries no warehouse, so branch scope here is the
company plus the branch's own cost centres — the same basis
`branch_filters` uses for accounting documents.
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, nowdate

from yht_custom import report_scope

#: Debit-positive roots. Everything else reads credit-positive.
_DEBIT_POSITIVE = ("Asset", "Expense")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	account = filters.get("account")
	if not account:
		frappe.throw(_("Select an Account"))

	from_date = getdate(filters.get("from_date") or add_months(nowdate(), -12))
	to_date = getdate(filters.get("to_date") or nowdate())
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	company = report_scope.company_filter(filters)
	sign = _sign(account)

	opening = _opening(account, company, from_date, sign)
	entries = _entries(account, company, from_date, to_date)

	rows = [
		{
			"posting_date": from_date,
			"remarks": _("Opening Balance"),
			"debit": 0,
			"credit": 0,
			"balance": opening,
			"is_opening": 1,
		}
	]
	balance = opening
	for entry in entries:
		balance += sign * (flt(entry.debit) - flt(entry.credit))
		entry["balance"] = balance
		rows.append(entry)

	rows.append(
		{
			"posting_date": to_date,
			"remarks": _("Closing Balance"),
			"debit": sum(flt(e.get("debit")) for e in entries),
			"credit": sum(flt(e.get("credit")) for e in entries),
			"balance": balance,
			"is_opening": 1,
		}
	)
	return _columns(), rows


def _sign(account):
	root = frappe.db.get_value("Account", account, "root_type")
	return 1 if root in _DEBIT_POSITIVE else -1


def _columns():
	return [
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
		{
			"label": _("Voucher No"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link",
			"options": "voucher_type", "width": 160,
		},
		{"label": _("Voucher Type"), "fieldname": "voucher_type", "fieldtype": "Data", "width": 130},
		{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Small Text", "width": 320},
		{"label": _("Debit"), "fieldname": "debit", "fieldtype": "Currency", "width": 130},
		{"label": _("Credit"), "fieldname": "credit", "fieldtype": "Currency", "width": 130},
		{"label": _("Balance"), "fieldname": "balance", "fieldtype": "Currency", "width": 140},
	]


def _opening(account, company, from_date, sign):
	where = ["gle.is_cancelled = 0", "gle.account = %(account)s", "gle.posting_date < %(from_date)s"]
	params = {"account": account, "from_date": from_date}
	if company:
		where.append("gle.company = %(company)s")
		params["company"] = company

	row = frappe.db.sql(
		f"""SELECT IFNULL(SUM(gle.debit), 0) dr, IFNULL(SUM(gle.credit), 0) cr
		    FROM `tabGL Entry` gle WHERE {' AND '.join(where)}""",
		params,
		as_dict=True,
	)[0]
	return sign * (flt(row.dr) - flt(row.cr))


def _entries(account, company, from_date, to_date):
	where = [
		"gle.is_cancelled = 0",
		"gle.account = %(account)s",
		"gle.posting_date BETWEEN %(from_date)s AND %(to_date)s",
	]
	params = {"account": account, "from_date": from_date, "to_date": to_date}
	if company:
		where.append("gle.company = %(company)s")
		params["company"] = company

	return frappe.db.sql(
		f"""
		SELECT gle.posting_date, gle.voucher_type, gle.voucher_no,
		       gle.debit, gle.credit,
		       -- `remarks` is empty on a great many rows; the party or the account's
		       -- own against-string is what an operator actually reads.
		       COALESCE(NULLIF(TRIM(gle.remarks), ''), NULLIF(TRIM(gle.party), ''),
		                NULLIF(TRIM(gle.against), ''), '') AS remarks
		FROM `tabGL Entry` gle
		WHERE {' AND '.join(where)}
		ORDER BY gle.posting_date, gle.creation
		""",
		params,
		as_dict=True,
	)
