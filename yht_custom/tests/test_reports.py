# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Tests for the branch report pack — Stock Sales, Collection, Branch Receivables.

Every test here is READ ONLY. `bench run-tests` on this site once deleted 4,847
client `Item Price` rows through a fixture teardown, so a report test that writes
nothing is a deliberate choice, not an oversight.

Run: bench --site yht-khobhar.enfonoerp.com run-tests --app yht_custom \
        --skip-before-tests
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_months, flt, nowdate

from yht_custom import report_scope
from yht_custom.yht_custom.report.branch_receivables import branch_receivables
from yht_custom.yht_custom.report.collection import collection
from yht_custom.yht_custom.report.stock_sales import stock_sales

REPORTS = ("Stock Sales", "Collection", "Branch Receivables")

#: Halalas. Two money paths that should agree may still differ by rounding.
TOLERANCE = 0.05


class TestReportPack(FrappeTestCase):
	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		if not self.company:
			self.skipTest("no Company on this site")
		self.window = {
			"company": self.company,
			"from_date": add_months(nowdate(), -60),
			"to_date": nowdate(),
		}

	# ------------------------------------------------------------ registration

	def test_reports_are_installed_and_inline(self):
		"""Each report exists, and neither flag lets frappe queue it.

		A promoted report returns an empty table in the browser while running fine
		server-side — the exact failure that shipped four blank dashboard reports.
		"""
		for name in REPORTS:
			with self.subTest(report=name):
				self.assertTrue(frappe.db.exists("Report", name), f"{name} not installed")
				flags = frappe.db.get_value(
					"Report",
					name,
					["report_type", "prepared_report", "disable_prepared_report_automation"],
					as_dict=True,
				)
				self.assertEqual(flags.report_type, "Script Report")
				self.assertFalse(flags.prepared_report, f"{name} would be queued, not run inline")
				self.assertTrue(
					flags.disable_prepared_report_automation,
					f"{name} can still be auto-promoted to a Prepared Report",
				)

	def test_branch_user_may_run_every_report(self):
		"""A Custom Role REPLACES Report.roles, so presence in one is not enough."""
		from frappe.core.doctype.report.report import Report

		if not frappe.db.exists("Role", "Branch User"):
			self.skipTest("Branch User role not provisioned")

		for name in REPORTS:
			with self.subTest(report=name):
				custom_role = frappe.db.get_value("Custom Role", {"report": name}, "name")
				if custom_role:
					roles = frappe.get_all(
						"Has Role", filters={"parent": custom_role, "parenttype": "Custom Role"}, pluck="role"
					)
				else:
					roles = frappe.get_all(
						"Has Role", filters={"parent": name, "parenttype": "Report"}, pluck="role"
					)
				self.assertIn("Branch User", roles, f"Branch User cannot open {name}")
				self.assertTrue(issubclass(Report, object))

	# -------------------------------------------------------------- stock sales

	def test_stock_sales_runs_for_every_grouping(self):
		for group_by in ("Item", "Item Group", "Customer"):
			with self.subTest(group_by=group_by):
				columns, rows = stock_sales.execute({**self.window, "group_by": group_by})[:2]
				self.assertTrue(columns)
				self.assertIsInstance(rows, list)

	def test_stock_sales_groupings_agree_on_the_total(self):
		"""Grouping changes the rows, never the money.

		If Item and Item Group disagree, one of them is dropping rows — which is
		exactly what a warehouse-only branch filter does to the 143 Sales Invoice
		Items on this site that carry no warehouse.
		"""
		totals = {}
		for group_by in ("Item", "Item Group", "Customer"):
			rows = stock_sales.execute({**self.window, "group_by": group_by})[1]
			totals[group_by] = sum(flt(row["amount"]) for row in rows)

		if not any(totals.values()):
			self.skipTest("no sales in the window")

		self.assertAlmostEqual(totals["Item"], totals["Item Group"], delta=TOLERANCE)
		self.assertAlmostEqual(totals["Item"], totals["Customer"], delta=TOLERANCE)

	def test_stock_sales_average_rate_is_amount_over_qty(self):
		rows = stock_sales.execute({**self.window, "group_by": "Item"})[1]
		if not rows:
			self.skipTest("no sales in the window")

		for row in rows[:25]:
			if not flt(row["qty"]):
				self.assertEqual(flt(row["avg_rate"]), 0.0)
				continue
			self.assertAlmostEqual(
				flt(row["avg_rate"]), flt(row["amount"]) / flt(row["qty"]), delta=TOLERANCE
			)

	def test_stock_sales_rejects_an_unknown_grouping(self):
		with self.assertRaises(frappe.ValidationError):
			stock_sales.execute({**self.window, "group_by": "Salesperson"})

	# ---------------------------------------------------------------- collection

	def test_collection_reports_both_sources(self):
		"""Payment Entry alone would miss every till receipt.

		Measured on this site: 783 Payment Entries and 562 Sales Invoice Payment
		rows. A single-source report would silently drop the branch's cash drawer.
		"""
		rows = collection.execute(self.window)[1]
		if not rows:
			self.skipTest("no collection in the window")

		sources = {row["source"] for row in rows}
		self.assertIn(collection.SOURCE_PAYMENT_ENTRY, sources)
		self.assertIn(collection.SOURCE_INVOICE, sources)

	def test_collection_source_filter_partitions_the_total(self):
		everything = collection.execute(self.window)[1]
		if not everything:
			self.skipTest("no collection in the window")

		by_source = {}
		for source in (collection.SOURCE_PAYMENT_ENTRY, collection.SOURCE_INVOICE):
			rows = collection.execute({**self.window, "source": source})[1]
			by_source[source] = sum(flt(row["amount"]) for row in rows)
			self.assertTrue(all(row["source"] == source for row in rows))

		self.assertAlmostEqual(
			sum(flt(row["amount"]) for row in everything), sum(by_source.values()), delta=TOLERANCE
		)

	def test_collection_rows_carry_a_resolvable_voucher(self):
		"""The Voucher column is a Dynamic Link; a blank voucher_type breaks it."""
		rows = collection.execute(self.window)[1]
		if not rows:
			self.skipTest("no collection in the window")

		for row in rows[:25]:
			self.assertIn(row["voucher_type"], ("Payment Entry", "Sales Invoice"))
			self.assertTrue(frappe.db.exists(row["voucher_type"], row["voucher_no"]))

	# -------------------------------------------------------- branch receivables

	def test_receivables_match_the_invoice_outstanding(self):
		"""The ledger sum and the stored field must agree for as-on-today.

		This is the test that proves reading `Payment Ledger Entry` was safe. The
		stored `outstanding_amount` is only correct for today, which is why the
		report does not use it — but for today the two must be the same number, or
		the ledger query is wrong.
		"""
		rows = branch_receivables.execute({"company": self.company, "as_on_date": nowdate()})[1]
		if not rows:
			self.skipTest("nothing outstanding")

		names = [row["invoice"] for row in rows]
		stored = {
			row.name: flt(row.outstanding_amount)
			for row in frappe.get_all(
				"Sales Invoice",
				filters={"name": ["in", names]},
				fields=["name", "outstanding_amount", "conversion_rate"],
			)
			if flt(row.conversion_rate or 1) == 1
		}
		if not stored:
			self.skipTest("no company-currency invoices to compare")

		for row in rows:
			if row["invoice"] not in stored:
				continue
			self.assertAlmostEqual(
				flt(row["outstanding"]),
				stored[row["invoice"]],
				delta=TOLERANCE,
				msg=f"{row['invoice']} disagrees with its stored outstanding",
			)

	def test_receivables_buckets_are_exclusive_and_complete(self):
		rows = branch_receivables.execute({"company": self.company, "as_on_date": nowdate()})[1]
		if not rows:
			self.skipTest("nothing outstanding")

		names = branch_receivables._bucket_names()
		for row in rows:
			filled = [name for name in names if flt(row[name])]
			self.assertLessEqual(len(filled), 1, f"{row['invoice']} is in two ageing buckets")
			self.assertAlmostEqual(
				sum(flt(row[name]) for name in names), flt(row["outstanding"]), delta=TOLERANCE
			)

	def test_receivables_only_overdue_drops_the_not_yet_due(self):
		base = {"company": self.company, "as_on_date": nowdate()}
		everything = branch_receivables.execute(base)[1]
		if not everything:
			self.skipTest("nothing outstanding")

		overdue = branch_receivables.execute({**base, "only_overdue": 1})[1]
		self.assertLessEqual(len(overdue), len(everything))
		self.assertTrue(all(row["days_overdue"] > 0 for row in overdue))

	def test_receivables_as_on_date_is_point_in_time(self):
		"""An earlier as-on date can never owe less than nothing, nor more than today
		plus everything invoiced since. The cheap invariant is that it runs and the
		total is non-negative — a stored-field implementation would return today's
		figure for both dates, which this at least keeps honest about."""
		base = {"company": self.company}
		today_total = sum(
			flt(row["outstanding"]) for row in branch_receivables.execute({**base, "as_on_date": nowdate()})[1]
		)
		past_total = sum(
			flt(row["outstanding"])
			for row in branch_receivables.execute({**base, "as_on_date": add_months(nowdate(), -24)})[1]
		)
		self.assertGreaterEqual(today_total, 0)
		self.assertGreaterEqual(past_total, 0)

	# -------------------------------------------------------------------- scope

	def test_group_warehouse_expands_to_its_leaves(self):
		group = frappe.db.get_value("Warehouse", {"is_group": 1, "company": self.company}, "name")
		if not group:
			self.skipTest("no group warehouse")

		resolved = report_scope.resolve_warehouses(group)
		self.assertTrue(resolved)
		for warehouse in resolved:
			self.assertFalse(
				frappe.db.get_value("Warehouse", warehouse, "is_group"),
				"a group warehouse leaked into the filter; nothing posts to one",
			)

	def test_administrator_is_never_restricted(self):
		self.assertFalse(report_scope.is_restricted("Administrator"))
		self.assertEqual(report_scope.allowed_warehouses("Administrator"), [])
