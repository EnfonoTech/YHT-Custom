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


def _purchased_item():
	return frappe.db.get_value("Purchase Invoice Item", {"docstatus": 1, "rate": [">", 0]}, "item_code")


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


class TestPurchaseHistory(FrappeTestCase):
	"""The buying counterpart of the price history, behind its own button."""

	def test_returns_rows(self):
		item = _purchased_item()
		if not item:
			self.skipTest("no submitted purchase history on this site")
		out = price_assist.get_purchase_history(item, company=_company(), limit=5)
		self.assertIsInstance(out, dict)
		self.assertIn("rows", out)
		self.assertIsInstance(out["rows"], list)

	def test_rows_carry_what_the_table_prints(self):
		"""Pins the payload against the columns `purchase_table` renders.

		The selling table drifted once already — the API returned a bare list while the JS
		expected {rows, summary}, and the only symptom was an empty table on screen. Assert
		the keys rather than discovering a blank column in a demo.
		"""
		item = _purchased_item()
		if not item:
			self.skipTest("no submitted purchase history on this site")
		rows = price_assist.get_purchase_history(item, company=_company(), limit=5)["rows"]
		if not rows:
			self.skipTest("no purchase rows in this branch's warehouses")
		for key in ("invoice", "posting_date", "supplier", "supplier_name",
		            "qty", "uom", "rate", "base_rate", "currency", "bill_no"):
			self.assertIn(key, rows[0], f"purchase_table renders {key}")

	def test_every_row_is_submitted(self):
		"""A draft purchase is not a price we paid."""
		item = _purchased_item()
		if not item:
			self.skipTest("no submitted purchase history on this site")
		rows = price_assist.get_purchase_history(item, company=_company(), limit=20)["rows"]
		for row in rows:
			self.assertEqual(
				frappe.db.get_value("Purchase Invoice", row["invoice"], "docstatus"), 1,
				f"{row['invoice']} is not submitted",
			)

	def test_rows_are_for_the_item_asked_for(self):
		item = _purchased_item()
		if not item:
			self.skipTest("no submitted purchase history on this site")
		rows = price_assist.get_purchase_history(item, company=_company(), limit=20)["rows"]
		for row in rows:
			self.assertTrue(
				frappe.db.exists(
					"Purchase Invoice Item",
					{"parent": row["invoice"], "item_code": item},
				),
				f"{row['invoice']} carries no row for {item}",
			)

	def test_newest_first(self):
		item = _purchased_item()
		if not item:
			self.skipTest("no submitted purchase history on this site")
		rows = price_assist.get_purchase_history(item, company=_company(), limit=20)["rows"]
		dates = [str(r["posting_date"]) for r in rows]
		self.assertEqual(dates, sorted(dates, reverse=True), "purchases must read newest first")

	def test_limit_is_honoured(self):
		item = _purchased_item()
		if not item:
			self.skipTest("no submitted purchase history on this site")
		self.assertLessEqual(len(price_assist.get_purchase_history(item, company=_company(), limit=2)["rows"]), 2)

	def test_blank_item_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			price_assist.get_purchase_history("")

	def test_it_gates_on_purchase_invoice_not_sales_invoice(self):
		"""🔴 THE PERMISSION THAT MATTERS.

		`get_price_history` gates on Sales Invoice. Copying that here would hand supplier
		prices to any role that can sell — the whole reason this is a separate endpoint with
		its own check. Branch User holds both reads on this site, so assert the CALL, not the
		role: patch has_permission and confirm which doctype it was asked about.
		"""
		asked = []
		original = frappe.has_permission

		def spy(doctype, *args, **kwargs):
			asked.append(doctype)
			return original(doctype, *args, **kwargs)

		frappe.has_permission = spy
		try:
			price_assist.get_purchase_history(_purchased_item() or "NO SUCH ITEM", company=_company(), limit=1)
		except Exception:
			pass
		finally:
			frappe.has_permission = original

		self.assertIn("Purchase Invoice", asked)
		self.assertNotIn("Sales Invoice", asked)
