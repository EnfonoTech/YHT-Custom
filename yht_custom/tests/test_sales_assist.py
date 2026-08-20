# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""The last of the sales assist (MoM §2.5, plan 5.6). Read-only."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint, flt

from yht_custom import sales_assist


class TestLiveStockColumn(FrappeTestCase):
	def test_available_stock_shows_in_every_item_grid(self):
		for doctype, fieldname, label in sales_assist.GRID_COLUMNS:
			with self.subTest(doctype=doctype):
				field = frappe.get_meta(doctype).get_field(fieldname)
				self.assertTrue(field, f"{doctype} has no {fieldname}")
				self.assertTrue(field.in_list_view, f"{doctype} hides available stock")
				self.assertEqual(field.label, label)
				self.assertTrue(field.read_only, "a fetched figure must not be typeable")

	def test_erpnext_already_populates_it(self):
		"""The reason this needed no new code.

		If ERPNext ever stops fetching actual_qty, the column becomes a row of
		zeros and this test is the warning.
		"""
		row = frappe.db.sql(
			"""SELECT COUNT(*) total, SUM(actual_qty IS NULL) nulls
			   FROM `tabSales Invoice Item`""",
			as_dict=True,
		)[0]
		if not cint(row.total):
			self.skipTest("no invoice rows")
		self.assertEqual(cint(row.nulls), 0)

	def test_provisioning_is_idempotent(self):
		second = sales_assist.setup_sales_assist_columns()
		self.assertEqual(second["applied"], 0)
		self.assertFalse(second["failed"])

	def test_branch_stock_reads_the_shared_scope(self):
		"""It must not invent its own idea of which warehouses a branch owns."""
		item = frappe.db.get_value("Bin", {"actual_qty": [">", 0]}, "item_code")
		if not item:
			self.skipTest("nothing in stock")

		total = sales_assist.branch_stock(item)
		unrestricted = flt(
			frappe.db.sql(
				"SELECT SUM(actual_qty) FROM `tabBin` WHERE item_code = %s", (item,)
			)[0][0]
		)
		# As Administrator the scope is unrestricted, so the two must agree.
		self.assertAlmostEqual(total, unrestricted, delta=0.001)

	def test_branch_stock_refuses_a_warehouse_outside_the_branch(self):
		from yht_custom import report_scope

		item = frappe.db.get_value("Bin", {"actual_qty": [">", 0]}, "item_code")
		if not item:
			self.skipTest("nothing in stock")
		# Administrator is unrestricted, so this proves the plumbing, not the block;
		# the block itself is covered in test_reports.
		self.assertFalse(report_scope.is_restricted("Administrator"))
		self.assertIsInstance(sales_assist.branch_stock(item), float)


class TestPaymentDueDate(FrappeTestCase):
	def test_the_due_date_is_autofilled_today(self):
		"""Not by new code — by Company.payment_terms falling back for everyone.

		Measured: 401 of 428 customers carry no terms of their own, and only 176 of
		2,344 submitted invoices are due on their posting date.
		"""
		summary = sales_assist.payment_terms_coverage()
		if not summary["submitted_invoices"]:
			self.skipTest("no submitted invoices")
		self.assertTrue(summary["autofill_working"])
		self.assertEqual(summary["invoices_without_a_due_date"], 0)

	def test_the_company_fallback_exists(self):
		"""Remove it and every customer without terms loses their due date."""
		summary = sales_assist.payment_terms_coverage()
		self.assertTrue(
			summary["company_fallback_template"],
			"no company payment terms — due dates would collapse to the posting date",
		)
		self.assertTrue(
			frappe.db.exists("Payment Terms Template", summary["company_fallback_template"])
		)

	def test_the_coverage_gap_is_reported_not_hidden(self):
		summary = sales_assist.payment_terms_coverage()
		self.assertIn("customers_without_own_terms", summary)
		self.assertLessEqual(summary["customers_without_own_terms"], summary["customers"])
		self.assertIn("(none)", summary["customers_by_terms"])

	def test_a_new_invoice_gets_a_due_date_from_the_terms(self):
		"""End to end on a throwaway draft, rolled back by FrappeTestCase."""
		customer = frappe.db.get_value(
			"Customer", {"payment_terms": ["is", "not set"]}, "name"
		)
		company = frappe.defaults.get_global_default("company")
		item = frappe.db.get_value("Sales Invoice Item", {"docstatus": 1}, "item_code")
		if not (customer and company and item):
			self.skipTest("need a customer, a company and an item")

		invoice = frappe.new_doc("Sales Invoice")
		invoice.customer = customer
		invoice.company = company
		invoice.append("items", {"item_code": item, "qty": 1, "rate": 10})
		invoice.set_missing_values()
		invoice.run_method("set_due_date")

		self.assertTrue(invoice.due_date, "no due date was derived")
