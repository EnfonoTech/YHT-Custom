# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""The import gate (plan 7.1). Read-only except the snapshot round-trip.

The gate is EXPECTED TO FAIL on this data — that is the point of building it. The
tests assert that it fails for the right reasons and with the right numbers, so a
future run that passes means the data was fixed rather than the check broken.
"""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from yht_custom import import_gate

#: Documented in docs/00-STUDY-AND-PLAN.md §2.4 and re-measured 2026-08-20.
KNOWN_GL_GAP = 3000.00
KNOWN_STOCK_GAP = 74409.27
KNOWN_NEGATIVE_BINS = 102


class TestGateShape(FrappeTestCase):
	def test_every_check_returns_a_verdict(self):
		rows = import_gate.run_checks()
		self.assertEqual(len(rows), len(import_gate.CHECKS))
		for row in rows:
			with self.subTest(check=row["key"]):
				self.assertIn(row["status"], ("PASS", "FAIL", "ERROR"))
				self.assertIn("measured", row)

	def test_no_check_errors(self):
		"""ERROR means the check could not run — never read it as a pass.

		One did: comparing `b.stock_value` against a SELECT alias raised
		"Unknown column 's.sle_value' in 'WHERE'", and only the ERROR status made it
		visible instead of a silent pass.
		"""
		errored = [r for r in import_gate.run_checks() if r["status"] == "ERROR"]
		self.assertFalse(errored, f"checks could not run: {[r['key'] for r in errored]}")

	def test_the_gate_fails_while_the_data_is_broken(self):
		self.assertFalse(import_gate.gate_passes())

	def test_only_blocking_failures_decide_the_gate(self):
		rows = import_gate.run_checks()
		blocking_failed = [r for r in rows if r["blocking"] and r["status"] != "PASS"]
		self.assertEqual(import_gate.gate_passes(), not blocking_failed)


class TestGateNumbers(FrappeTestCase):
	def _check(self, key):
		return next(r for r in import_gate.run_checks() if r["key"] == key)

	def test_the_gl_gap_is_still_exactly_three_thousand(self):
		self.assertAlmostEqual(flt(self._check("gl_balanced")["difference"]), KNOWN_GL_GAP, delta=0.05)

	def test_the_gl_gap_traces_to_one_voucher(self):
		row = self._check("gl_voucher_balanced")
		self.assertEqual(flt(row["difference"]), 1.0)
		self.assertIn("KS-JV-26-0074", row["detail"])

	def test_the_accounting_equation_agrees_about_the_size_of_the_hole(self):
		"""Two independent routes to the same number, or one of them is wrong."""
		self.assertAlmostEqual(
			flt(self._check("accounting_equation")["difference"]), KNOWN_GL_GAP, delta=0.05
		)

	def test_the_stock_to_gl_gap_is_unchanged(self):
		self.assertAlmostEqual(
			flt(self._check("stock_ties_to_gl")["difference"]), KNOWN_STOCK_GAP, delta=0.05
		)

	def test_the_negative_bin_count_is_unchanged(self):
		self.assertEqual(flt(self._check("no_negative_stock")["difference"]), KNOWN_NEGATIVE_BINS)

	def test_the_stock_ledger_agrees_with_itself(self):
		"""The gap is between stock and GL, NOT inside the stock ledger.

		Measured against the wrong basis — SUM(actual_qty) — this reported 1,863 of
		2,820 bins broken. This site has 3,469 Stock Reconciliation rows, every one
		with actual_qty = 0, because a reconciliation sets qty_after_transaction
		absolutely. Against the latest ledger row, nothing disagrees.
		"""
		self.assertEqual(flt(self._check("bin_agrees_with_ledger")["difference"]), 0.0)

	def test_reconciliations_really_do_carry_zero_actual_qty(self):
		"""The premise of the check above. If it changes, the basis must change."""
		rows = frappe.db.sql(
			"""SELECT COUNT(*) total, SUM(actual_qty = 0) zero FROM `tabStock Ledger Entry`
			   WHERE is_cancelled = 0 AND voucher_type = 'Stock Reconciliation'""",
			as_dict=True,
		)[0]
		if not rows.total:
			self.skipTest("no Stock Reconciliation rows")
		self.assertEqual(flt(rows.zero), flt(rows.total))

	def test_valuation_method_is_uniform_since_step_3(self):
		self.assertEqual(self._check("valuation_method_uniform")["status"], "PASS")


class TestSnapshots(FrappeTestCase):
	LABELS = ("_test_gate_before", "_test_gate_after")

	def tearDown(self):
		for label in self.LABELS:
			path = import_gate._snapshot_path(label)
			if os.path.exists(path):
				os.remove(path)

	def test_a_snapshot_covers_every_bin(self):
		rows = import_gate.snapshot()
		self.assertEqual(len(rows), frappe.db.count("Bin"))
		self.assertTrue(all("item_code" in row and "warehouse" in row for row in rows))

	def test_two_snapshots_of_the_same_data_show_no_movement(self):
		"""The pre/post acceptance test must be quiet when nothing changed."""
		for label in self.LABELS:
			import_gate.save_snapshot(label)

		result = import_gate.compare_snapshots(*self.LABELS)
		self.assertEqual(result["qty_changed"], 0)
		self.assertEqual(result["value_changed_only"], 0)
		self.assertEqual(result["appeared"], 0)
		self.assertEqual(result["vanished"], 0)
		self.assertAlmostEqual(result["total_value_delta"], 0.0, delta=0.05)

	def test_a_snapshot_name_is_sanitised(self):
		"""The label reaches the filesystem, so it must not carry a path."""
		path = import_gate._snapshot_path("../../etc/passwd")
		self.assertNotIn("..", path)
		self.assertTrue(path.endswith("etcpasswd.json"))

	def test_a_blank_snapshot_name_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			import_gate._snapshot_path("///")


class TestGateReports(FrappeTestCase):
	def test_both_reports_are_installed_and_run_inline(self):
		for name in ("Import Gate", "Stock Valuation Snapshot"):
			with self.subTest(report=name):
				flags = frappe.db.get_value(
					"Report", name, ["prepared_report", "disable_prepared_report_automation"], as_dict=True
				)
				self.assertTrue(flags, f"{name} is not installed")
				self.assertFalse(flags.prepared_report)
				self.assertTrue(flags.disable_prepared_report_automation)

	def test_the_gate_report_renders_a_verdict(self):
		from yht_custom.yht_custom.report.import_gate import import_gate as report

		columns, rows, _msg, _chart, summary = report.execute({})
		self.assertTrue(columns)
		self.assertEqual(len(rows), len(import_gate.CHECKS))
		self.assertEqual(summary[0]["label"], "Verdict")
		self.assertIn("GATE", summary[0]["value"])

	def test_the_snapshot_report_only_problems_filter_narrows(self):
		from yht_custom.yht_custom.report.stock_valuation_snapshot import (
			stock_valuation_snapshot as report,
		)

		everything = report.execute({})[1]
		problems = report.execute({"only_problems": 1})[1]
		self.assertLess(len(problems), len(everything))
		self.assertGreater(len(problems), 0, "this data definitely has problems")

	def test_the_snapshot_report_is_not_branch_scoped(self):
		"""A migration instrument, not an operator screen — roles gate it instead."""
		roles = frappe.get_all("Has Role", filters={"parent": "Stock Valuation Snapshot"}, pluck="role")
		self.assertNotIn("Branch User", roles)
		self.assertIn("Accounts Manager", roles)
