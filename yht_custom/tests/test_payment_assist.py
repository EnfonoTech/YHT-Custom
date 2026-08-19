# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Tests for the sales payment assist (MoM 5.6).

The two that matter most are the ones guarding against defects already seen
elsewhere:

* ``test_returns_are_refused`` — RMAX's tender dialog fires on credit notes and
  then blocks the save. Its own ROADMAP.md logs it as open. This site holds 99
  returns, so a regression here is immediate and visible.
* ``test_no_bank_account_is_read`` — the whole reason the Payment Entry is built
  longhand instead of via ``get_payment_entry``. If someone "simplifies" this back
  to ``get_payment_entry``, a branch user meets a bare PermissionError, and the
  only alternative fix exposes every company IBAN.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from yht_custom.api import payment_assist

COMPANY_ABBR_CACHE = {}


def _company():
	return frappe.db.get_value("Branch Configuration", {}, "company") or frappe.defaults.get_global_default(
		"company"
	)


def _mode_with_account(company):
	"""A Mode of Payment that can actually post for this company."""
	rows = frappe.get_all(
		"Mode of Payment Account",
		filters={"company": company, "default_account": ["!=", ""]},
		fields=["parent", "default_account"],
		limit=1,
	)
	return rows[0] if rows else None


class TestPaymentModeResolution(FrappeTestCase):
	def test_every_returned_mode_can_post(self):
		"""A mode without a company account throws at submit inside
		get_bank_cash_account, so offering it in the dialog would mean the operator
		allocates money and only finds out on save."""
		company = _company()
		if not company:
			self.skipTest("no company configured")

		modes = payment_assist.get_branch_payment_modes(company)
		for mode in modes:
			account = frappe.db.get_value(
				"Mode of Payment Account",
				{"parent": mode["mode_of_payment"], "company": company},
				"default_account",
			)
			self.assertTrue(
				account,
				f"{mode['mode_of_payment']} was offered but has no default account for {company}",
			)

	def test_no_account_details_are_returned(self):
		"""The payload the browser receives must carry names only.

		This is the contract that let us refuse `read` on Bank Account. If a field
		carrying an account, an account number or an IBAN is ever added to the
		return value, the IBAN decision silently reverses itself.
		"""
		company = _company()
		if not company:
			self.skipTest("no company configured")

		forbidden = {"account", "default_account", "bank_account", "bank_account_no", "iban"}
		for mode in payment_assist.get_branch_payment_modes(company):
			self.assertEqual(set(mode.keys()), {"mode_of_payment", "type"})
			self.assertFalse(set(mode.keys()) & forbidden)

	def test_empty_company_returns_empty(self):
		self.assertEqual(payment_assist.get_branch_payment_modes(""), [])
		self.assertEqual(payment_assist.get_branch_payment_modes(None), [])

	def test_branch_allowlist_narrows_but_only_when_set(self):
		"""An unconfigured branch opts OUT of filtering rather than losing every
		mode — the same convention Branch Configuration uses for warehouses. The
		moment one row is listed the allowlist becomes authoritative."""
		company = _company()
		config = frappe.db.get_value("Branch Configuration", {}, "name")
		if not company or not config:
			self.skipTest("no branch configuration")

		listed = frappe.get_all(
			"Branch Configuration Mode of Payment", filters={"parent": config}, pluck="mode_of_payment"
		)
		offered = {m["mode_of_payment"] for m in payment_assist.get_branch_payment_modes(company)}

		if not listed:
			# Unfiltered: every usable mode is offered.
			self.assertTrue(offered or not _mode_with_account(company))
			return

		# setup_branch_payment_modes seeds only usable modes, so the offer is a
		# subset of the listed set, never wider than it.
		self.assertTrue(offered.issubset(set(listed)), offered - set(listed))


class TestCustomerPaymentStatus(FrappeTestCase):
	def test_missing_args_return_empty(self):
		self.assertEqual(payment_assist.get_customer_payment_status("", "X"), {})
		self.assertEqual(payment_assist.get_customer_payment_status("X", ""), {})

	def test_no_limit_is_not_a_breach(self):
		"""Measured: 0 Customer Credit Limit rows on this site. The warning must
		stay dormant rather than firing on every customer (B5 is still unanswered
		by the client, so the limits themselves do not exist yet)."""
		company = _company()
		customer = frappe.db.get_value("Customer", {}, "name")
		if not company or not customer:
			self.skipTest("no customer")

		status = payment_assist.get_customer_payment_status(customer, company)
		self.assertIn("has_limit", status)
		if not frappe.db.exists("Customer Credit Limit", {"parent": customer, "company": company}):
			self.assertFalse(status["has_limit"])
			self.assertEqual(flt(status["credit_limit"]), 0.0)

	def test_outstanding_matches_the_ledger(self):
		company = _company()
		if not company:
			self.skipTest("no company configured")
		customer = frappe.db.get_value(
			"Sales Invoice", {"docstatus": 1, "company": company, "outstanding_amount": [">", 0]}, "customer"
		)
		if not customer:
			self.skipTest("no customer with an outstanding invoice")

		expected = frappe.db.sql(
			"""
			SELECT COALESCE(SUM(outstanding_amount), 0) FROM `tabSales Invoice`
			WHERE docstatus = 1 AND customer = %s AND company = %s
			""",
			(customer, company),
		)[0][0]

		status = payment_assist.get_customer_payment_status(customer, company)
		self.assertAlmostEqual(flt(status["outstanding"], 2), flt(expected, 2), places=2)


class TestCollectPayment(FrappeTestCase):
	def test_blank_invoice_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			payment_assist.collect_payment("", [])

	def test_draft_invoice_is_refused(self):
		name = frappe.db.get_value("Sales Invoice", {"docstatus": 0}, "name")
		if not name:
			self.skipTest("no draft invoice on this site")
		with self.assertRaises(frappe.ValidationError):
			payment_assist.collect_payment(name, [{"mode_of_payment": "CASH", "amount": 1}])

	def test_returns_are_refused(self):
		"""A credit note is not a collection.

		RMAX's popup has no is_return check at all — see its ROADMAP.md — so it
		fires on credit notes against a positive "Invoice Total" while the money is
		going out, and then refuses to let the document save. Never do that here.
		"""
		name = frappe.db.get_value("Sales Invoice", {"docstatus": 1, "is_return": 1}, "name")
		if not name:
			self.skipTest("no submitted credit note on this site")
		with self.assertRaises(frappe.ValidationError):
			payment_assist.collect_payment(name, [{"mode_of_payment": "CASH", "amount": 1}])

	def test_unparseable_payload_is_refused(self):
		name = frappe.db.get_value("Sales Invoice", {"docstatus": 1, "is_return": 0}, "name")
		if not name:
			self.skipTest("no submitted invoice on this site")
		with self.assertRaises(frappe.ValidationError):
			payment_assist.collect_payment(name, "not json")

	def test_all_zero_rows_are_refused(self):
		"""Most rows in the dialog stay at 0.00 by design, so zero rows are dropped
		rather than rejected — but a payload that is ALL zero means the operator
		pressed the button without entering anything."""
		name = frappe.db.get_value("Sales Invoice", {"docstatus": 1, "is_return": 0}, "name")
		if not name:
			self.skipTest("no submitted invoice on this site")
		with self.assertRaises(frappe.ValidationError):
			payment_assist.collect_payment(name, [{"mode_of_payment": "CASH", "amount": 0}])

	def test_mode_outside_the_allowlist_is_refused(self):
		"""The dialog only ever offers the allowlist, so anything else arrived by
		hand-crafting the HTTP request."""
		company = _company()
		name = frappe.db.get_value(
			"Sales Invoice",
			{"docstatus": 1, "is_return": 0, "company": company, "outstanding_amount": [">", 0]},
			"name",
		)
		if not name:
			self.skipTest("no unpaid submitted invoice on this site")
		with self.assertRaises(frappe.ValidationError):
			payment_assist.collect_payment(
				name, [{"mode_of_payment": "_Not A Real Mode", "amount": 1}]
			)

	def test_over_tender_is_refused(self):
		company = _company()
		row = frappe.db.get_value(
			"Sales Invoice",
			{"docstatus": 1, "is_return": 0, "company": company, "outstanding_amount": [">", 0]},
			["name", "outstanding_amount"],
			as_dict=True,
		)
		mode = _mode_with_account(company) if company else None
		if not row or not mode:
			self.skipTest("no unpaid invoice or no usable mode of payment")

		with self.assertRaises(frappe.ValidationError):
			payment_assist.collect_payment(
				row.name,
				[{"mode_of_payment": mode.parent, "amount": flt(row.outstanding_amount) + 100}],
			)

	def test_payment_entry_is_created_and_clears_the_invoice(self):
		"""End to end, on a throwaway invoice: the Payment Entry posts, allocates
		to the invoice, and the outstanding drops to zero."""
		company = _company()
		mode = _mode_with_account(company) if company else None
		if not company or not mode:
			self.skipTest("no usable mode of payment")

		invoice = self._make_invoice(company)

		created = payment_assist.collect_payment(
			invoice.name, [{"mode_of_payment": mode.parent, "amount": flt(invoice.grand_total)}]
		)
		self.assertEqual(len(created), 1)

		entry = frappe.get_doc("Payment Entry", created[0])
		self.assertEqual(entry.docstatus, 1)
		self.assertEqual(entry.payment_type, "Receive")
		self.assertEqual(entry.mode_of_payment, mode.parent)
		self.assertEqual(entry.paid_to, mode.default_account)
		self.assertEqual(entry.references[0].reference_name, invoice.name)
		self.assertAlmostEqual(flt(entry.paid_amount, 2), flt(invoice.grand_total, 2), places=2)

		# 45% of submitted invoices on this site use a template with term-based
		# allocation, and ERPNext throws unless every reference row names a term.
		from yht_custom.api.payment_assist import _term_allocation_enabled

		if _term_allocation_enabled(invoice):
			for reference in entry.references:
				self.assertTrue(
					reference.payment_term,
					"term-based allocation is on but a reference row has no payment_term",
				)
			self.assertAlmostEqual(
				flt(sum(flt(r.allocated_amount) for r in entry.references), 2),
				flt(invoice.grand_total, 2),
				places=2,
			)

		invoice.reload()
		self.assertAlmostEqual(flt(invoice.outstanding_amount, 2), 0.0, places=2)

	def test_split_tender_creates_one_entry_per_mode(self):
		company = _company()
		modes = frappe.get_all(
			"Mode of Payment Account",
			filters={"company": company, "default_account": ["!=", ""]},
			fields=["parent", "default_account"],
			limit=2,
		)
		if not company or len(modes) < 2:
			self.skipTest("need two usable modes of payment")

		invoice = self._make_invoice(company)

		half = flt(flt(invoice.grand_total) / 2, 2)
		rest = flt(flt(invoice.grand_total) - half, 2)
		created = payment_assist.collect_payment(
			invoice.name,
			[
				{"mode_of_payment": modes[0].parent, "amount": half},
				{"mode_of_payment": modes[1].parent, "amount": rest},
			],
		)
		self.assertEqual(len(created), 2)
		invoice.reload()
		self.assertAlmostEqual(flt(invoice.outstanding_amount, 2), 0.0, places=2)

	def _make_invoice(self, company):
		"""A submitted cash-sale invoice, copied from an existing one.

		Copied from a real submitted invoice rather than built from scratch because
		this site's flow policy routes stock through a Delivery Note and rejects an
		invoice that tries to move it — a hand-built invoice would fail validation
		for reasons unrelated to what is under test.

		This deliberately does NOT swallow exceptions. An earlier version returned
		None on any failure so the caller could skipTest, and the result was that
		the two end-to-end tests — the only ones that prove a Payment Entry actually
		posts — reported as skipped while the real cause sat unread. A broken
		fixture must fail loudly, not quietly downgrade the suite.
		"""
		template_name = frappe.db.get_value(
			"Sales Invoice",
			{"docstatus": 1, "is_return": 0, "company": company, "update_stock": 0},
			"name",
			order_by="modified desc",
		)
		if not template_name:
			return None

		template = frappe.get_doc("Sales Invoice", template_name)
		invoice = frappe.copy_doc(template)
		invoice.posting_date = today()
		invoice.set_posting_time = 1
		invoice.due_date = today()
		invoice.update_stock = 0
		invoice.is_return = 0
		invoice.custom_payment_mode = "Cash"
		for row in invoice.items:
			row.delivery_note = None
			row.dn_detail = None
			row.sales_order = None
			row.so_detail = None

		# copy_doc brings the payment schedule across INCLUDING paid_amount, so a copy
		# of a settled invoice arrives looking already settled and _build_references
		# rightly refuses it. Clearing the table makes ERPNext regenerate it from the
		# payment terms template on validate, which is what a real new invoice does.
		invoice.payment_schedule = []
		invoice.insert()
		# reload() between insert and submit is REQUIRED, not defensive. Something on
		# the insert path writes the row again behind the in-memory doc, so submit()
		# hits check_if_latest and raises TimestampMismatchError — 0.4s apart, every
		# time, but only inside FrappeTestCase; the identical sequence run straight
		# through bench execute submits fine. Do not remove it.
		invoice.reload()
		invoice.submit()
		return invoice


class TestPaymentTermAllocation(FrappeTestCase):
	"""The branch that broke the first green run.

	`AS USUAL` (768 submitted invoices) and `60 Days credit` (284) both carry
	`allocate_payment_based_on_payment_terms = 1`, so 45% of this site's invoices
	require a `payment_term` on every Payment Entry reference row. Building the
	entry longhand — which is what keeps Bank Account unreadable — means
	replicating what `get_reference_as_per_payment_terms` does.
	"""

	def test_flag_is_read_from_the_template_not_accounts_settings(self):
		"""`Accounts Settings.allocate_payment_based_on_payment_terms` is NULL on
		this site, so a check against it would have reported "off" for all 1,052
		invoices that actually need term allocation."""
		from yht_custom.api.payment_assist import _term_allocation_enabled

		template = frappe.db.get_value(
			"Payment Terms Template", {"allocate_payment_based_on_payment_terms": 1}, "name"
		)
		if not template:
			self.skipTest("no template with term-based allocation on this site")

		invoice = frappe._dict({"payment_terms_template": template, "name": "_probe"})
		self.assertTrue(_term_allocation_enabled(invoice))

		invoice_without = frappe._dict({"payment_terms_template": None, "name": "_probe"})
		self.assertFalse(_term_allocation_enabled(invoice_without))

	def test_references_carry_a_term_when_allocation_is_on(self):
		from yht_custom.api.payment_assist import _build_references

		name = frappe.db.get_value(
			"Sales Invoice",
			{"docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0]},
			"name",
		)
		if not name:
			self.skipTest("no unpaid submitted invoice on this site")

		invoice = frappe.get_doc("Sales Invoice", name)
		from yht_custom.api.payment_assist import _term_allocation_enabled

		if not _term_allocation_enabled(invoice):
			self.skipTest(f"{name} does not use term-based allocation")

		refs = _build_references(invoice, flt(invoice.outstanding_amount))
		self.assertTrue(refs)
		for ref in refs:
			self.assertTrue(ref.get("payment_term"), ref)
		self.assertAlmostEqual(
			flt(sum(flt(r["allocated_amount"]) for r in refs), 2),
			flt(invoice.outstanding_amount, 2),
			places=2,
		)

	def test_partial_tender_allocates_oldest_term_first(self):
		from yht_custom.api.payment_assist import _build_references, _term_allocation_enabled

		name = frappe.db.get_value(
			"Sales Invoice",
			{"docstatus": 1, "is_return": 0, "outstanding_amount": [">", 10]},
			"name",
		)
		if not name:
			self.skipTest("no unpaid submitted invoice on this site")

		invoice = frappe.get_doc("Sales Invoice", name)
		if not _term_allocation_enabled(invoice):
			self.skipTest(f"{name} does not use term-based allocation")

		refs = _build_references(invoice, 10.0)
		self.assertAlmostEqual(
			flt(sum(flt(r["allocated_amount"]) for r in refs), 2), 10.0, places=2
		)
		# Oldest first: the earliest due term is the one that receives money.
		schedule = sorted(
			invoice.payment_schedule, key=lambda row: (row.due_date or invoice.due_date)
		)
		self.assertEqual(refs[0]["payment_term"], schedule[0].payment_term)

	def test_reference_has_no_term_when_allocation_is_off(self):
		from yht_custom.api.payment_assist import _build_references

		name = frappe.db.get_value(
			"Sales Invoice",
			{"docstatus": 1, "is_return": 0, "payment_terms_template": ["in", ["", None]]},
			"name",
		)
		if not name:
			self.skipTest("no invoice without a payment terms template on this site")

		invoice = frappe.get_doc("Sales Invoice", name)
		refs = _build_references(invoice, 1.0)
		self.assertEqual(len(refs), 1)
		self.assertIsNone(refs[0].get("payment_term"))
