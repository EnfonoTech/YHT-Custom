# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Tests for the form trimming.

The regression these guard against is specific and was live for a week: the price
list was relocated on Sales Invoice, Delivery Note and Purchase Invoice but NOT on
Sales Order, Quotation or Purchase Receipt — where it was still sitting inside the
`Currency and Price List` accordion. Hiding that accordion, which is what makes the
screens clean, would therefore have hidden the price list on those three.

So the two facts are tested together: the section is hidden AND the price list is
outside it.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom.form_layout import (
	HIDE_FIELDS,
	MOVE_AFTER,
	_CURRENCY_SECTION,
	setup_form_layout,
)

PRICE_LIST_FIELD = {
	"Sales Invoice": "selling_price_list",
	"Sales Order": "selling_price_list",
	"Delivery Note": "selling_price_list",
	"Quotation": "selling_price_list",
	"Purchase Invoice": "buying_price_list",
	"Purchase Receipt": "buying_price_list",
}


class TestFormLayout(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		setup_form_layout()
		frappe.clear_cache()

	def test_every_hidden_field_exists(self):
		"""A fieldname that does not exist is hidden silently and forever — the
		Property Setter is written, nothing errors, and the field it was meant to
		hide stays visible. Two such typos shipped on this app before."""
		for doctype, fieldnames in HIDE_FIELDS.items():
			if not frappe.db.exists("DocType", doctype):
				continue
			meta = frappe.get_meta(doctype)
			for fieldname in fieldnames:
				self.assertIsNotNone(
					meta.get_field(fieldname), f"{doctype}.{fieldname} does not exist in this version"
				)

	def test_every_move_anchor_exists(self):
		"""`update_stock` exists only on Sales Invoice and Purchase Invoice, and
		Quotation has no header warehouse at all, so the anchors legitimately
		differ per doctype. A wrong anchor is a silent no-op."""
		for doctype, moves in MOVE_AFTER.items():
			if not frappe.db.exists("DocType", doctype):
				continue
			meta = frappe.get_meta(doctype)
			for fieldname, anchor in moves:
				self.assertIsNotNone(meta.get_field(fieldname), f"{doctype}.{fieldname}")
				self.assertIsNotNone(meta.get_field(anchor), f"{doctype}.{anchor} (anchor)")

	def test_currency_section_is_hidden_everywhere(self):
		for doctype in PRICE_LIST_FIELD:
			if not frappe.db.exists("DocType", doctype):
				continue
			field = frappe.get_meta(doctype).get_field("currency_and_price_list")
			self.assertIsNotNone(field, doctype)
			self.assertTrue(field.hidden, f"{doctype}: the Currency and Price List section is visible")

	def test_price_list_is_outside_the_hidden_section(self):
		"""THE ONE THAT MATTERS. Hiding a Section Break hides everything between it
		and the next section break, so a price list left inside disappears."""
		for doctype, price_field in PRICE_LIST_FIELD.items():
			if not frappe.db.exists("DocType", doctype):
				continue
			meta = frappe.get_meta(doctype)
			order = [df.fieldname for df in meta.fields]
			self.assertIn(price_field, order, doctype)

			start = order.index("currency_and_price_list")
			inside = []
			for fieldname in order[start + 1 :]:
				field = meta.get_field(fieldname)
				if field and field.fieldtype in ("Section Break", "Tab Break"):
					break
				inside.append(fieldname)

			self.assertNotIn(
				price_field,
				inside,
				f"{doctype}: {price_field} is still inside the hidden Currency and Price List section",
			)

	def test_price_list_is_visible(self):
		for doctype, price_field in PRICE_LIST_FIELD.items():
			if not frappe.db.exists("DocType", doctype):
				continue
			field = frappe.get_meta(doctype).get_field(price_field)
			self.assertFalse(field.hidden, f"{doctype}.{price_field} is hidden")

	def test_price_list_sits_next_to_its_anchor(self):
		for doctype, moves in MOVE_AFTER.items():
			if not frappe.db.exists("DocType", doctype):
				continue
			order = [df.fieldname for df in frappe.get_meta(doctype).fields]
			for fieldname, anchor in moves:
				if fieldname not in order or anchor not in order:
					continue
				self.assertEqual(
					order.index(fieldname),
					order.index(anchor) + 1,
					f"{doctype}: {fieldname} is not immediately after {anchor}",
				)

	def test_section_members_are_hidden_individually_too(self):
		"""Belt and braces: hiding the section break is enough for the form, but a
		report column, a search or a print format can still reach a field whose own
		`hidden` is 0."""
		for fieldname in _CURRENCY_SECTION:
			for doctype in PRICE_LIST_FIELD:
				if not frappe.db.exists("DocType", doctype):
					continue
				field = frappe.get_meta(doctype).get_field(fieldname)
				if not field:
					continue
				self.assertTrue(field.hidden, f"{doctype}.{fieldname}")

	def test_is_idempotent(self):
		"""Runs on every after_migrate, so a second run must change nothing."""
		before = frappe.db.count("Property Setter")
		setup_form_layout()
		self.assertEqual(frappe.db.count("Property Setter"), before)
