# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Tests for Price Assist and the extended Price History payload."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from yht_custom.api import price_assist


def _company():
	return frappe.db.get_value("Branch Configuration", {}, "company") or frappe.defaults.get_global_default(
		"company"
	)


def _sold_item():
	return frappe.db.get_value("Sales Invoice Item", {"docstatus": 1, "rate": [">", 0]}, "item_code")


class TestPriceHistoryPayload(FrappeTestCase):
	def test_returns_rows_and_summary(self):
		"""The shape changed from a bare list to ``{rows, summary}``.

		Both JS call sites were updated together; this pins the contract so a future
		simplification back to a list is caught here rather than by an empty table on screen.
		"""
		item = _sold_item()
		if not item:
			self.skipTest("no submitted sales history on this site")
		out = price_assist.get_price_history(item, company=_company(), limit=5)
		self.assertIsInstance(out, dict)
		self.assertIn("rows", out)
		self.assertIn("summary", out)
		self.assertIsInstance(out["rows"], list)
		self.assertIsInstance(out["summary"], dict)

	def test_summary_carries_buying_and_stock(self):
		item = _sold_item()
		if not item:
			self.skipTest("no submitted sales history on this site")
		summary = price_assist.get_price_history(item, company=_company(), limit=1)["summary"]
		for key in (
			"last_purchase_rate",
			"last_purchase_date",
			"buying_price_list",
			"buying_price_list_rate",
			"valuation_rate",
			"available_qty",
			"reserved_qty",
			"stock",
			"stock_uom",
		):
			self.assertIn(key, summary, f"{key} missing from the summary")
		self.assertIsInstance(summary["stock"], list)

	def test_available_qty_matches_the_stock_rows(self):
		"""The headline figure must be the sum of what the table below it shows."""
		item = _sold_item()
		if not item:
			self.skipTest("no submitted sales history on this site")
		summary = price_assist.get_price_history(item, company=_company(), limit=1)["summary"]
		self.assertAlmostEqual(
			flt(summary["available_qty"], 3),
			flt(sum(flt(r.get("actual_qty")) for r in summary["stock"]), 3),
			places=3,
		)

	def test_blank_item_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			price_assist.get_price_history("")

	def test_last_purchase_never_breaks_the_dialog(self):
		"""A reporting extra must not take down the answer the operator is waiting on.

		``get_last_purchase_details`` is wrapped, so an item it cannot price still returns a
		summary with a None rate rather than raising.
		"""
		item = frappe.db.get_value("Item", {"disabled": 0}, "name")
		if not item:
			self.skipTest("no items")
		summary = price_assist._buying_and_stock(item, _company(), [])
		self.assertIn("last_purchase_rate", summary)
