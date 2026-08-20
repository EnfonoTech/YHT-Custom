# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Customer Statement (MoM §2.6) and the dashboard tile it fixes."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_months, flt, nowdate

from yht_custom.yht_custom.report.customer_statement import customer_statement

BRANCH_USER = "branchtest@yht-khobhar.enfonoerp.com"
TOLERANCE = 0.05


class TestCustomerStatement(FrappeTestCase):
	def setUp(self):
		self.company = frappe.defaults.get_global_default("company") or frappe.db.get_value(
			"Company", {}, "name"
		)
		self.customer = frappe.db.get_value(
			"Sales Invoice", {"docstatus": 1, "outstanding_amount": [">", 0]}, "customer"
		)
		if not self.customer:
			self.skipTest("no customer with an outstanding invoice")
		self.filters = {
			"company": self.company,
			"customer": self.customer,
			"from_date": add_months(nowdate(), -240),
			"to_date": nowdate(),
		}

	def test_a_customer_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			customer_statement.execute({"company": self.company})

	def test_the_statement_opens_and_closes_with_a_total_row(self):
		rows = customer_statement.execute(self.filters)[1]
		self.assertGreaterEqual(len(rows), 2)
		self.assertTrue(rows[0]["is_total"])
		self.assertTrue(rows[-1]["is_total"])
		self.assertEqual(rows[0]["particulars"], "Opening Balance")
		self.assertEqual(rows[-1]["particulars"], "Closing Balance")

	def test_the_closing_balance_equals_the_customer_ledger(self):
		"""A statement that does not foot to the ledger is not a statement.

		Over a window wide enough to cover everything, the closing balance must
		equal the customer's whole receivable position.
		"""
		rows = customer_statement.execute(self.filters)[1]
		ledger = flt(
			frappe.db.sql(
				"""SELECT ROUND(SUM(debit) - SUM(credit), 2) FROM `tabGL Entry`
				   WHERE is_cancelled = 0 AND party_type = 'Customer'
				     AND party = %s AND company = %s""",
				(self.customer, self.company),
			)[0][0]
		)
		self.assertAlmostEqual(flt(rows[-1]["balance"]), ledger, delta=TOLERANCE)

	def test_the_running_balance_actually_runs(self):
		rows = customer_statement.execute(self.filters)[1]
		body = rows[1:-1]
		if not body:
			self.skipTest("no movement in the window")

		balance = flt(rows[0]["balance"])
		for row in body:
			balance += flt(row["debit"]) - flt(row["credit"])
			self.assertAlmostEqual(flt(row["balance"]), balance, delta=TOLERANCE)

	def test_the_summary_reconciles(self):
		summary = customer_statement.execute(self.filters)[4]
		values = {row["label"]: flt(row["value"]) for row in summary}
		self.assertAlmostEqual(
			values["Opening"] + values["Invoiced"] - values["Received"],
			values["Closing"],
			delta=TOLERANCE,
		)

	def test_it_is_built_on_the_ledger_not_on_invoices(self):
		"""An invoice-based statement misses journals, write-offs and on-account
		payments. The report must therefore surface voucher types beyond invoices
		wherever the ledger has them."""
		types = frappe.db.sql(
			"""SELECT DISTINCT voucher_type FROM `tabGL Entry`
			   WHERE is_cancelled = 0 AND party_type = 'Customer' AND party = %s""",
			(self.customer,),
			pluck=True,
		)
		rows = customer_statement.execute(self.filters)[1]
		shown = {row["voucher_type"] for row in rows if row["voucher_type"]}
		self.assertTrue(shown.issubset(set(types)))
		self.assertTrue(shown)

	def test_vouchers_resolve_as_dynamic_links(self):
		rows = customer_statement.execute(self.filters)[1]
		for row in rows[1:-1][:20]:
			with self.subTest(voucher=row["voucher_no"]):
				self.assertTrue(frappe.db.exists(row["voucher_type"], row["voucher_no"]))


class TestStatementAccess(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_branch_user_is_refused_a_customer_they_never_dealt_with(self):
		"""Access is gated on the customer, not on filtering the rows.

		A branch-filtered subset would produce a "balance" that reconciles against
		nothing and that the customer would dispute.
		"""
		if not frappe.db.exists("User", BRANCH_USER):
			self.skipTest("no branch user")

		company = frappe.defaults.get_global_default("company")
		stranger = frappe.db.sql(
			"""SELECT name FROM `tabCustomer`
			   WHERE name NOT IN (SELECT DISTINCT customer FROM `tabSales Invoice`
			                      WHERE docstatus = 1 AND customer IS NOT NULL)
			   LIMIT 1""",
			pluck=True,
		)
		if not stranger:
			self.skipTest("every customer has an invoice")

		frappe.clear_cache(user=BRANCH_USER)
		frappe.set_user(BRANCH_USER)
		with self.assertRaises(frappe.ValidationError):
			customer_statement.execute(
				{
					"company": company,
					"customer": stranger[0],
					"from_date": add_months(nowdate(), -12),
					"to_date": nowdate(),
				}
			)


class TestDashboardTiles(FrappeTestCase):
	def test_the_statement_tile_no_longer_opens_general_ledger(self):
		"""The tile said Customer Statement and opened General Ledger for weeks."""
		import os

		path = os.path.join(
			frappe.get_app_path("yht_custom"), "yht_custom", "page", "yht_dashboard", "yht_dashboard.js"
		)
		with open(path) as handle:
			source = handle.read()
		self.assertIn('label: "Customer Statement", desc: "One customer, aged", report: "Customer Statement"', source)
		self.assertNotIn('label: "Customer Statement", desc: "Account statements", report: "General Ledger"', source)

	def test_every_report_a_tile_links_to_exists(self):
		"""A tile pointing at a missing report is a dead end for an operator."""
		import os
		import re

		path = os.path.join(
			frappe.get_app_path("yht_custom"), "yht_custom", "page", "yht_dashboard", "yht_dashboard.js"
		)
		with open(path) as handle:
			source = handle.read()
		for name in set(re.findall(r'report:\s*"([^"]+)"', source)):
			with self.subTest(report=name):
				self.assertTrue(frappe.db.exists("Report", name), f"tile points at missing {name}")

	def test_a_branch_user_may_open_every_tile_report(self):
		if not frappe.db.exists("Role", "Branch User"):
			self.skipTest("no Branch User role")

		import os
		import re

		path = os.path.join(
			frappe.get_app_path("yht_custom"), "yht_custom", "page", "yht_dashboard", "yht_dashboard.js"
		)
		with open(path) as handle:
			source = handle.read()

		for name in sorted(set(re.findall(r'report:\s*"([^"]+)"', source))):
			with self.subTest(report=name):
				custom_role = frappe.db.get_value("Custom Role", {"report": name}, "name")
				parent, parenttype = (
					(custom_role, "Custom Role") if custom_role else (name, "Report")
				)
				roles = frappe.get_all(
					"Has Role", filters={"parent": parent, "parenttype": parenttype}, pluck="role"
				)
				self.assertIn("Branch User", roles, f"Branch User cannot open {name}")
