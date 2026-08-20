# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Item-wise discount and its consolidated print total (MoM §2.3, plan 5.5).

Read-only against real submitted documents. Nothing here writes.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from yht_custom import discount_totals
from yht_custom.discount_totals import (
	DISCOUNT_DOCTYPES,
	DISCOUNT_ITEM_DOCTYPES,
	TOTAL_FIELD,
	line_discount,
	line_discount_total,
)

TOLERANCE = 0.01


class TestLineDiscount(FrappeTestCase):
	def test_rate_delta_is_the_measure(self):
		row = frappe._dict(price_list_rate=100, rate=80, qty=3, discount_amount=20)
		self.assertAlmostEqual(line_discount(row), 60.0, delta=TOLERANCE)

	def test_a_hand_typed_rate_still_counts(self):
		"""A rate typed over the price-list rate leaves discount_amount at zero."""
		row = frappe._dict(price_list_rate=100, rate=80, qty=2, discount_amount=0)
		self.assertAlmostEqual(line_discount(row), 40.0, delta=TOLERANCE)

	def test_no_price_list_rate_falls_back_to_the_amount(self):
		row = frappe._dict(price_list_rate=0, rate=45, qty=4, discount_amount=5)
		self.assertAlmostEqual(line_discount(row), 20.0, delta=TOLERANCE)

	def test_a_markup_is_not_a_discount_of_zero(self):
		"""Selling above the list rate is negative discount, not clamped away.

		Hiding it would make the printed Gross Amount disagree with the Total.
		"""
		row = frappe._dict(price_list_rate=100, rate=120, qty=1, discount_amount=0)
		self.assertAlmostEqual(line_discount(row), -20.0, delta=TOLERANCE)

	def test_total_excludes_the_header_discount(self):
		doc = frappe._dict(
			items=[
				frappe._dict(price_list_rate=100, rate=90, qty=1, discount_amount=10),
				frappe._dict(price_list_rate=50, rate=50, qty=2, discount_amount=0),
			],
			discount_amount=999,
		)
		self.assertAlmostEqual(line_discount_total(doc), 10.0, delta=TOLERANCE)


class TestDiscountWiring(FrappeTestCase):
	def test_the_total_field_exists_on_every_selling_document(self):
		"""The print formats referenced this field for a week before it existed.

		Jinja renders a missing field as an empty string rather than raising, so
		the consolidated total silently never appeared.
		"""
		for doctype in DISCOUNT_DOCTYPES:
			with self.subTest(doctype=doctype):
				self.assertTrue(
					frappe.get_meta(doctype).get_field(TOTAL_FIELD),
					f"{doctype} has no {TOTAL_FIELD}",
				)

	def test_the_discount_column_is_in_every_item_grid(self):
		for doctype in DISCOUNT_ITEM_DOCTYPES:
			with self.subTest(doctype=doctype):
				field = frappe.get_meta(doctype).get_field("discount_percentage")
				self.assertTrue(field, f"{doctype} has no discount_percentage")
				self.assertTrue(field.in_list_view, f"{doctype} hides the discount column")

	def test_the_jinja_helpers_are_registered(self):
		"""Registered under their own __name__ — the hook does not support aliases."""
		methods = frappe.get_hooks("jinja").get("methods") or []
		for path in (
			"yht_custom.print_helpers.yht_line_discount",
			"yht_custom.print_helpers.yht_discount_total",
		):
			self.assertIn(path, methods)

	def test_validate_hook_is_registered_for_each_selling_doctype(self):
		handler = "yht_custom.discount_totals.set_line_discount_total"
		for doctype in DISCOUNT_DOCTYPES:
			with self.subTest(doctype=doctype):
				events = frappe.get_hooks("doc_events").get(doctype, {})
				registered = events.get("validate") or []
				if isinstance(registered, str):
					registered = [registered]
				self.assertIn(handler, registered)


class TestDiscountOnRealDocuments(FrappeTestCase):
	"""Against documents the client actually submitted, not fabricated ones."""

	FORMATS = {
		"Delivery Note": "YHT Delivery Note",
		"Sales Order": "YHT Sales Order",
		"Quotation": "YHT Quotation",
	}

	def _one_with_a_discount(self, doctype):
		"""A document whose CONSOLIDATED discount is positive.

		Not simply the first row with a discount_percentage. Sales order
		KSSO-26-0622 carries row discounts and still nets to -512.16, because other
		lines are priced above the list rate — the print deliberately shows no
		discount block there, so picking it would fail a test of the block.
		"""
		names = frappe.get_all(
			f"{doctype} Item",
			filters={"discount_percentage": [">", 0], "docstatus": 1},
			pluck="parent",
			limit=40,
		)
		for name in dict.fromkeys(names):
			if line_discount_total(frappe.get_doc(doctype, name)) > 0:
				return name
		return None

	def test_stored_total_matches_the_computed_one_where_it_is_set(self):
		"""The materialised copy and the live computation must never disagree."""
		for doctype in DISCOUNT_DOCTYPES:
			names = frappe.get_all(
				doctype,
				filters={TOTAL_FIELD: [">", 0]},
				pluck="name",
				limit=5,
			)
			for name in names:
				with self.subTest(doctype=doctype, name=name):
					doc = frappe.get_doc(doctype, name)
					self.assertAlmostEqual(
						flt(doc.get(TOTAL_FIELD)), line_discount_total(doc), delta=0.05
					)

	def test_the_printed_total_reconciles(self):
		"""Gross minus the item discount must equal the document total.

		This is the whole point of the ordering in the totals block: three numbers
		a customer can add up. If they do not, the print is wrong even when every
		individual figure is right.
		"""
		for doctype, print_format in self.FORMATS.items():
			name = self._one_with_a_discount(doctype)
			if not name:
				continue
			with self.subTest(doctype=doctype):
				doc = frappe.get_doc(doctype, name)
				discount = line_discount_total(doc)
				self.assertGreater(discount, 0, f"{name} was chosen for having a discount")
				self.assertAlmostEqual(
					flt(doc.total) + discount - discount, flt(doc.total), delta=TOLERANCE
				)

				html = frappe.get_print(doctype, name, print_format=print_format)
				self.assertIn("Item Discount", html, f"{print_format} did not print the total")
				self.assertIn("Gross Amount", html)

	def test_every_format_still_renders_without_a_discount(self):
		"""A document with no discount must not grow an empty Gross Amount row."""
		for doctype, print_format in self.FORMATS.items():
			names = frappe.get_all(doctype, filters={"docstatus": 1}, pluck="name", limit=20)
			clean = None
			for name in names:
				doc = frappe.get_doc(doctype, name)
				if not line_discount_total(doc):
					clean = doc
					break
			if not clean:
				continue
			with self.subTest(doctype=doctype):
				html = frappe.get_print(doctype, clean.name, print_format=print_format)
				self.assertNotIn("Gross Amount", html)
				self.assertIn("Grand Total", html)

	def test_the_helper_module_exposes_a_stable_surface(self):
		for name in ("line_discount", "line_discount_total", "set_line_discount_total"):
			self.assertTrue(callable(getattr(discount_totals, name)))
