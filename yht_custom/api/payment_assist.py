# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Sales-side payment assist — MoM 5.6.

Three jobs, all read-only except the last:

1. ``get_branch_payment_modes`` — which Modes of Payment this branch may tender
   against, resolved server-side.
2. ``get_customer_payment_status`` — outstanding, credit limit and the breach
   flag, so the operator sees the customer's position before committing a credit
   sale.
3. ``collect_payment`` — turn a tender split into submitted Payment Entries.

WHY THIS DOES NOT CALL ``get_payment_entry``
--------------------------------------------
RMAX's equivalent does, and on a branch user it dies with a bare
``PermissionError`` and no message. Traced through v15 on this bench:

    payment_entry.py:2961   pe.bank_account = <default company Bank Account>
    payment_entry.py:2973   pe.set_bank_account_data()
    payment_entry.py:254      if not self.bank_account: return     # the escape
    bank_account.py:142       frappe.has_permission("Bank Account", ptype="read",
                                                    doc=..., throw=True)

The check is only reached because ``get_payment_entry`` populates
``pe.bank_account`` from the company's default. On this site
``Saudi National Bank - KATC`` carries ``is_default = 1``, so it IS populated and
the throw DOES fire. ``get_bank_account_details`` re-reads with a hard
``throw=True``, which no ``ignore_permissions`` flag suppresses.

Granting ``read`` on Bank Account would clear it in one line, but Bank Account has
no permlevel split — ``read`` hands every branch operator the account number and
IBAN of every company account. So the Payment Entry is built here field by field
instead. Nothing in this module reads Bank Account, and nothing it returns to the
browser contains an account number, an IBAN or a GL account code: the dialog is
labelled with Mode of Payment names only.

CREDIT NOTES
------------
Returns are excluded deliberately. RMAX's tender dialog fires on every draft with
``custom_payment_mode == "Cash"`` and never checks ``is_return``, so it also
appears on credit notes and then refuses to let them save until the full amount is
allocated — logged as an open defect in RMAX's own ROADMAP.md. This site already
holds 99 returns, so the bug would land immediately. ``collect_payment`` throws on
a return and the client gate skips it.
"""

import json

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt, getdate

#: Roles that see every enabled mode, not just the branch's allowlist.
_UNRESTRICTED_ROLES = {
	"System Manager",
	"Accounts Manager",
	"Accounts User",
	"Sales Manager",
	"Sales Master Manager",
}


def _is_unrestricted(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	if roles & _UNRESTRICTED_ROLES:
		return True
	return "Branch User" not in roles


def _user_branch(user: str | None = None) -> str | None:
	"""The Branch Configuration row this user belongs to, if any."""
	user = user or frappe.session.user
	parents = frappe.get_all(
		"Branch Configuration User", filters={"user": user}, pluck="parent", limit=1
	)
	return parents[0] if parents else None


def _modes_with_account(company: str) -> set[str]:
	"""Modes carrying a default Cash/Bank account for this company.

	A mode without one cannot post: ``get_bank_cash_account`` throws. Offering it
	in the dialog would mean the operator allocates money and only finds out at
	submit. Measured on this site: 21 modes enabled, 8 usable.
	"""
	mode_account = frappe.qb.DocType("Mode of Payment Account")
	rows = (
		frappe.qb.from_(mode_account)
		.select(mode_account.parent)
		.distinct()
		.where(
			(mode_account.company == company)
			& mode_account.default_account.notnull()
			& (mode_account.default_account != "")
		)
	).run()
	return {r[0] for r in rows}


@frappe.whitelist()
def get_branch_payment_modes(company: str) -> list[dict]:
	"""Tenderable modes for the signed-in user.

	Returns ``[{"mode_of_payment": str, "type": str}]`` — names and Cash/Bank type
	only. No account, no account number, no IBAN.
	"""
	if not company:
		return []

	usable = _modes_with_account(company)
	if not usable:
		return []

	allowed = None
	if not _is_unrestricted():
		branch = _user_branch()
		if branch:
			listed = frappe.get_all(
				"Branch Configuration Mode of Payment",
				filters={"parent": branch},
				pluck="mode_of_payment",
			)
			# An unconfigured branch opts out of filtering rather than losing every
			# mode — the same convention Branch Configuration uses elsewhere. The
			# moment one row is listed, the allowlist is authoritative.
			if listed:
				allowed = set(listed)

	modes = frappe.get_all(
		"Mode of Payment",
		filters={"enabled": 1, "name": ["in", list(usable)]},
		fields=["name", "type"],
		order_by="type desc, name asc",
	)

	out = []
	for mode in modes:
		if allowed is not None and mode.name not in allowed:
			continue
		out.append({"mode_of_payment": mode.name, "type": mode.type or ""})
	return out


@frappe.whitelist()
def get_customer_payment_status(customer: str, company: str) -> dict:
	"""Outstanding, credit limit and breach flag for the sales screen.

	``frappe.has_permission`` is checked explicitly: this is a public HTTP endpoint
	and the answer leaks a customer's total exposure.
	"""
	if not customer or not company:
		return {}

	if not frappe.has_permission("Customer", "read", doc=customer):
		raise frappe.PermissionError

	invoice = frappe.qb.DocType("Sales Invoice")
	rows = (
		frappe.qb.from_(invoice)
		.select(Sum(invoice.outstanding_amount))
		.where(
			(invoice.docstatus == 1)
			& (invoice.customer == customer)
			& (invoice.company == company)
		)
	).run()
	outstanding = flt(rows[0][0]) if rows and rows[0] else 0.0

	limit_row = frappe.db.get_value(
		"Customer Credit Limit",
		{"parent": customer, "company": company},
		["credit_limit", "bypass_credit_limit_check"],
		as_dict=True,
	)
	credit_limit = flt(limit_row.credit_limit) if limit_row else 0.0
	bypass = bool(limit_row and limit_row.bypass_credit_limit_check)

	return {
		"customer": customer,
		"outstanding": outstanding,
		"credit_limit": credit_limit,
		"bypass_credit_limit_check": bypass,
		# No limit set is NOT a breach. Measured on this site: 0 Customer Credit
		# Limit rows exist, so this stays False everywhere until YHT sets limits
		# (blocker B5). The warning is wired and dormant, not missing.
		"has_limit": credit_limit > 0,
	}


def _resolve_mode_account(mode_of_payment: str, company: str) -> str:
	"""The GL account a mode posts to. Server-side only — never returned."""
	account = frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": mode_of_payment, "company": company},
		"default_account",
	)
	if not account:
		frappe.throw(
			_("Mode of Payment {0} has no default account for {1}.").format(
				frappe.bold(mode_of_payment), frappe.bold(company)
			)
		)
	return account


@frappe.whitelist()
def collect_payment(sales_invoice: str, payments: str | list) -> list[str]:
	"""Create and submit one Payment Entry per tendered mode.

	``payments``: ``[{"mode_of_payment": str, "amount": float}, ...]``.
	Rows with a non-positive amount are dropped, not rejected — the dialog shows
	every branch mode and most stay at 0.00.
	"""
	if not sales_invoice:
		frappe.throw(_("Sales Invoice is required."))

	invoice = frappe.get_doc("Sales Invoice", sales_invoice)

	# get_doc does not check read permission on its own.
	if not frappe.has_permission("Sales Invoice", "read", doc=invoice):
		raise frappe.PermissionError
	if not frappe.has_permission("Payment Entry", "create"):
		raise frappe.PermissionError

	if invoice.docstatus != 1:
		frappe.throw(
			_("{0} must be submitted before payment can be recorded.").format(invoice.name)
		)
	if invoice.is_return:
		# See the module docstring — a credit note is not a collection.
		frappe.throw(
			_("{0} is a credit note. Record a refund as a Payment Entry instead.").format(
				invoice.name
			)
		)

	if isinstance(payments, str):
		try:
			payments = json.loads(payments)
		except (ValueError, TypeError):
			frappe.throw(_("Could not read the payment rows."))
	if not isinstance(payments, (list, tuple)):
		frappe.throw(_("Could not read the payment rows."))

	rows = []
	for row in payments:
		mode = (row or {}).get("mode_of_payment")
		amount = flt((row or {}).get("amount"))
		if not mode or amount <= 0:
			continue
		rows.append({"mode_of_payment": mode, "amount": amount})

	if not rows:
		frappe.throw(_("Enter an amount against at least one mode of payment."))

	allowed = {m["mode_of_payment"] for m in get_branch_payment_modes(invoice.company)}
	for row in rows:
		if row["mode_of_payment"] not in allowed:
			# The dialog only ever offers the allowlist; anything else arrived by
			# hand-crafting the request.
			frappe.throw(
				_("Mode of Payment {0} is not available for your branch.").format(
					frappe.bold(row["mode_of_payment"])
				)
			)

	tendered = flt(sum(r["amount"] for r in rows), 2)
	outstanding = flt(invoice.outstanding_amount, 2)
	if tendered - outstanding > 0.01:
		frappe.throw(
			_("Tendered {0} is more than the outstanding {1} on {2}.").format(
				frappe.bold(tendered), frappe.bold(outstanding), invoice.name
			)
		)

	created = []
	for row in rows:
		created.append(_make_payment_entry(invoice, row["mode_of_payment"], row["amount"]))
	return created


def _make_payment_entry(invoice, mode_of_payment: str, amount: float) -> str:
	"""Build a Receive Payment Entry against one invoice, one mode.

	Written out longhand rather than via ``get_payment_entry`` so no Bank Account
	read is required — see the module docstring. Only the fields a single-currency
	customer receipt needs are set; the controller derives the rest.
	"""
	deposit_account = _resolve_mode_account(mode_of_payment, invoice.company)
	receivable = invoice.debit_to
	party_currency = frappe.get_cached_value("Account", receivable, "account_currency")
	deposit_currency = frappe.get_cached_value("Account", deposit_account, "account_currency")

	if party_currency != deposit_currency:
		# Out of scope: YHT trades in SAR only and every price list on this site is
		# SAR. Fail loudly rather than post a wrong exchange rate.
		frappe.throw(
			_("{0} and {1} are in different currencies. Record this payment manually.").format(
				frappe.bold(mode_of_payment), frappe.bold(invoice.currency)
			)
		)

	entry = frappe.new_doc("Payment Entry")
	entry.payment_type = "Receive"
	entry.company = invoice.company
	entry.posting_date = getdate(invoice.posting_date)
	entry.mode_of_payment = mode_of_payment
	entry.party_type = "Customer"
	entry.party = invoice.customer
	entry.paid_from = receivable
	entry.paid_from_account_currency = party_currency
	entry.paid_to = deposit_account
	entry.paid_to_account_currency = deposit_currency
	entry.paid_amount = amount
	entry.received_amount = amount
	entry.source_exchange_rate = 1
	entry.target_exchange_rate = 1
	entry.reference_no = invoice.name
	entry.reference_date = getdate(invoice.posting_date)
	if invoice.get("cost_center"):
		entry.cost_center = invoice.cost_center

	entry.append(
		"references",
		{
			"reference_doctype": "Sales Invoice",
			"reference_name": invoice.name,
			"due_date": invoice.get("due_date"),
			"total_amount": flt(invoice.grand_total),
			"outstanding_amount": flt(invoice.outstanding_amount),
			"allocated_amount": amount,
		},
	)

	entry.insert()
	entry.submit()
	return entry.name
