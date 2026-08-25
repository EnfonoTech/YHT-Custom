# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""KATC Party & Account Ledger — client sheet item 9.

    Party Type & Account wise Report keep -
    Date, voucher number, Remarks, Debit, Credit, Balance

Same six columns as item 8; the difference is what you point it at. Item 8 is
"show me one ACCOUNT". This is "show me one PARTY" — a customer or a supplier —
across whichever receivable/payable accounts their entries landed in, which is
the question someone asks when a customer rings up about their balance.

WHY IT IS A SEPARATE REPORT AND NOT A FILTER ON ITEM 8. A party's entries can sit
in more than one account, and an account holds more than one party. Folding both
into one screen means an operator has to know which of the two filters is the
authoritative one, and leaving both blank would silently print the whole company.
Two reports, each with one required filter, cannot be read the wrong way round.

BOTH FILTERS ARE ACCEPTED, PARTY IS REQUIRED. Adding an account narrows a party's
ledger to one account — useful when a customer is also a supplier and the two
balances have to be kept apart.

SIGN. With no account chosen the ledger is DEBIT-POSITIVE: an operator reading a
party ledger is asking "what do they owe us", and a customer's receivable rises
on a debit. Pick an account and the sign follows that account's `root_type`, as
item 8 does — so a supplier's payable reads positive as money owed rather than
negative as a liability balance. Stated because the two halves genuinely differ.
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, nowdate

from yht_custom import report_scope

_DEBIT_POSITIVE = ("Asset", "Expense")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	party_type = filters.get("party_type")
	party = filters.get("party")
	if not party_type or not party:
		frappe.throw(_("Select a Party Type and a Party"))

	from_date = getdate(filters.get("from_date") or add_months(nowdate(), -12))
	to_date = getdate(filters.get("to_date") or nowdate())
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	company = report_scope.company_filter(filters)
	account = filters.get("account")
	sign = _sign(account) if account else 1

	base = _conditions(party_type, party, account, company)
	opening = _opening(base, from_date, sign)
	entries = _entries(base, from_date, to_date)

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
		{
			"label": _("Account"), "fieldname": "account", "fieldtype": "Link",
			"options": "Account", "width": 220,
		},
		{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Small Text", "width": 300},
		{"label": _("Debit"), "fieldname": "debit", "fieldtype": "Currency", "width": 130},
		{"label": _("Credit"), "fieldname": "credit", "fieldtype": "Currency", "width": 130},
		{"label": _("Balance"), "fieldname": "balance", "fieldtype": "Currency", "width": 140},
	]


def _conditions(party_type, party, account, company):
	where = ["gle.is_cancelled = 0", "gle.party_type = %(party_type)s", "gle.party = %(party)s"]
	params = {"party_type": party_type, "party": party}
	if account:
		where.append("gle.account = %(account)s")
		params["account"] = account
	if company:
		where.append("gle.company = %(company)s")
		params["company"] = company
	return where, params


def _opening(base, from_date, sign):
	where, params = base
	where = [*where, "gle.posting_date < %(from_date)s"]
	params = {**params, "from_date": from_date}
	row = frappe.db.sql(
		f"""SELECT IFNULL(SUM(gle.debit), 0) dr, IFNULL(SUM(gle.credit), 0) cr
		    FROM `tabGL Entry` gle WHERE {' AND '.join(where)}""",
		params,
		as_dict=True,
	)[0]
	return sign * (flt(row.dr) - flt(row.cr))


def _entries(base, from_date, to_date):
	where, params = base
	where = [*where, "gle.posting_date BETWEEN %(from_date)s AND %(to_date)s"]
	params = {**params, "from_date": from_date, "to_date": to_date}
	return frappe.db.sql(
		f"""
		SELECT gle.posting_date, gle.voucher_type, gle.voucher_no, gle.account,
		       gle.debit, gle.credit,
		       COALESCE(NULLIF(TRIM(gle.remarks), ''), NULLIF(TRIM(gle.against), ''), '') AS remarks
		FROM `tabGL Entry` gle
		WHERE {' AND '.join(where)}
		ORDER BY gle.posting_date, gle.creation
		""",
		params,
		as_dict=True,
	)
