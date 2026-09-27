# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Saudi national address and the Short Code title (plan 5.9)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import saudi_address

SAUDI = "Saudi Arabia"


class TestSaudiAddressFields(FrappeTestCase):
	def test_every_national_address_field_exists(self):
		"""Includes the two ksa_compliance owns — this app must not shadow them."""
		meta = frappe.get_meta("Address")
		for fieldname in (
			"address_line1",
			"address_line2",
			"city",
			"pincode",
			"custom_building_number",
			"custom_area",
			"custom_additional_number",
			"custom_unit_number",
			"custom_short_address",
		):
			with self.subTest(fieldname=fieldname):
				self.assertTrue(meta.get_field(fieldname), f"Address has no {fieldname}")

	def test_zatca_still_reads_the_fields_it_maps(self):
		"""ksa_compliance maps buyer_district off custom_area, not a field of ours.

		If this ever fails, an address form that looks complete is producing an
		e-invoice with an empty district.
		"""
		import inspect

		from ksa_compliance.ksa_compliance.doctype.sales_invoice_additional_fields import (
			sales_invoice_additional_fields as saf,
		)

		source = inspect.getsource(saf.SalesInvoiceAdditionalFields._set_buyer_address)
		self.assertIn("custom_area", source)
		self.assertIn("custom_building_number", source)
		self.assertIn("address_line1", source)


class TestSaudiAddressValidation(FrappeTestCase):
	def _address(self, **values):
		doc = frappe.new_doc("Address")
		doc.update(
			{
				"address_title": "_Test YHT Address",
				"address_type": "Billing",
				"address_line1": "King Fahd Road",
				"city": "Al Khobar",
				"country": SAUDI,
				**values,
			}
		)
		return doc

	def test_a_well_formed_address_validates(self):
		doc = self._address(
			custom_building_number="1234",
			custom_additional_number="5678",
			pincode="34421",
			custom_short_address="RQAA2929",
		)
		doc.run_method("validate")

	def test_a_short_building_number_is_rejected(self):
		doc = self._address(custom_building_number="12")
		with self.assertRaises(frappe.ValidationError):
			doc.run_method("validate")

	def test_a_seven_digit_postcode_is_rejected(self):
		"""'3463231' is real legacy data on this site, not an invented case."""
		doc = self._address(pincode="3463231")
		with self.assertRaises(frappe.ValidationError):
			doc.run_method("validate")

	def test_a_malformed_short_code_is_rejected(self):
		doc = self._address(custom_short_address="RQ2929")
		with self.assertRaises(frappe.ValidationError):
			doc.run_method("validate")

	def test_a_short_code_is_upper_cased(self):
		doc = self._address(custom_short_address="rqaa2929")
		doc.run_method("validate")
		self.assertEqual(doc.custom_short_address, "RQAA2929")

	def test_blank_fields_are_never_required_here(self):
		"""Presence is ZATCA's business. 579 of 579 addresses have no district."""
		doc = self._address()
		doc.run_method("validate")

	def test_a_non_saudi_address_is_left_alone(self):
		doc = self._address(country="Bahrain", pincode="00", custom_building_number="7")
		doc.run_method("validate")

	def test_the_country_name_with_arabic_still_counts_as_saudi(self):
		"""This site carries a Country literally named 'Saudi Arabia -<arabic>'."""
		doc = self._address(country="Saudi Arabia -المملكة العربية السعودية", pincode="00")
		with self.assertRaises(frappe.ValidationError):
			doc.run_method("validate")

	def test_existing_bad_data_stays_saveable_until_touched(self):
		"""A blanket throw would have made 50 legacy addresses unsaveable.

		Measured: 50 Saudi addresses carry a malformed pincode from the legacy
		import ("00", "3463231", "325478"). They must stay editable so somebody can
		fix the rest of the record.
		"""
		doc = self._address(pincode="00")
		doc.name = "_Test YHT Existing"
		# is_new() reads __islocal, not name — a doc with a name is still "new"
		# until this is cleared, and the check would fire anyway.
		doc.set("__islocal", 0)
		doc._doc_before_save = frappe._dict(doc.as_dict())
		self.assertFalse(doc.is_new())
		self.assertFalse(doc.has_value_changed("pincode"))
		saudi_address.validate(doc)

	def test_an_edited_bad_pincode_is_still_rejected(self):
		"""The escape hatch is for untouched data only."""
		doc = self._address(pincode="34421")
		doc.name = "_Test YHT Existing"
		doc.set("__islocal", 0)
		doc._doc_before_save = frappe._dict(doc.as_dict())
		doc.pincode = "00"
		with self.assertRaises(frappe.ValidationError):
			saudi_address.validate(doc)


class TestShortCodeTitle(FrappeTestCase):
	def test_the_short_code_becomes_the_title(self):
		doc = frappe.new_doc("Address")
		doc.update(
			{
				"address_title": "Some Customer Ltd",
				"address_type": "Billing",
				"country": SAUDI,
				"custom_short_address": "rqaa2929",
			}
		)
		saudi_address.before_insert(doc)
		self.assertEqual(doc.address_title, "RQAA2929")

	def test_no_short_code_leaves_the_title_alone(self):
		doc = frappe.new_doc("Address")
		doc.update({"address_title": "Some Customer Ltd", "address_type": "Billing", "country": SAUDI})
		saudi_address.before_insert(doc)
		self.assertEqual(doc.address_title, "Some Customer Ltd")

	def test_the_hooks_are_registered(self):
		events = frappe.get_hooks("doc_events").get("Address", {})
		for event, handler in (
			("validate", "yht_custom.saudi_address.validate"),
			("before_insert", "yht_custom.saudi_address.before_insert"),
		):
			registered = events.get(event) or []
			if isinstance(registered, str):
				registered = [registered]
			self.assertIn(handler, registered)


class TestAddressGapReport(FrappeTestCase):
	def test_the_gap_report_counts_the_real_site(self):
		summary = saudi_address.national_address_gaps()
		self.assertGreater(summary["addresses"], 0)
		self.assertGreaterEqual(summary["addresses"], summary["saudi"])
		for key in ("missing_district", "missing_building_number", "missing_postal_code"):
			self.assertGreaterEqual(summary[key], 0)


class TestTheSplAddressFlowEndToEnd(FrappeTestCase):
	"""CR-001 acceptance #5 — exercise the new code path, not just the validators.

	The parser itself is JavaScript and cannot run here. What CAN be asserted, and
	is what actually breaks in production, is the CONTRACT between it and the
	server: every field the parser writes must exist on Address, the value it puts
	in the district slot must be the one ZATCA reads, and an Address built from a
	real SPL line must save.

	The SPL line below is the shape `public/js/address.js` documents:

	    RQAA2929, 6823 Prince Sultan Road, 2929, Al Olaya, Riyadh, Riyadh, 12345
	"""

	SPL_LINE = "RQAA2929, 6823 Prince Sultan Road, 2929, Al Olaya, Riyadh, Riyadh, 12345"

	def _parsed(self):
		"""What `yht.address.parse` produces for SPL_LINE, in Python."""
		import re

		parts = [p.strip() for p in self.SPL_LINE.split(",")]
		match = re.match(r"^(\d{4})\s+(.*)$", parts[1])
		return {
			"custom_short_address": parts[0].upper(),
			"address_title": parts[0].upper(),
			"custom_building_number": match.group(1) if match else "",
			"address_line1": match.group(2).strip() if match else parts[1],
			"custom_additional_number": parts[2],
			"custom_area": parts[3],
			"city": parts[4],
			"state": parts[5],
			"pincode": parts[6],
		}

	def test_the_js_and_this_test_agree_on_the_field_list(self):
		"""A rename on either side must break something. Without this the test
		below would keep passing against a parser that writes somewhere else."""
		import os

		with open(
			os.path.join(frappe.get_app_path("yht_custom"), "public", "js", "address.js"),
			encoding="utf-8",
		) as handle:
			js = handle.read()
		for fieldname in self._parsed():
			with self.subTest(field=fieldname):
				self.assertIn(f"{fieldname}:", js, f"address.js no longer writes {fieldname}")

	def test_every_field_the_parser_writes_exists_on_address(self):
		meta = frappe.get_meta("Address")
		for fieldname in self._parsed():
			with self.subTest(field=fieldname):
				self.assertIsNotNone(meta.get_field(fieldname), f"{fieldname} is not on Address")

	def test_the_district_lands_where_zatca_reads_it(self):
		"""`ksa_compliance` hardcodes `custom_area` as `buyer_district`. This is the
		whole reason CR-002 resolved the way it did."""
		self.assertEqual(self._parsed()["custom_area"], "Al Olaya")

	def test_an_address_built_from_a_real_spl_line_saves_and_reads_back(self):
		values = self._parsed()
		doc = frappe.get_doc(
			dict(doctype="Address", address_type="Billing", country="Saudi Arabia", **values)
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Address", doc.name, force=1, ignore_permissions=True)

		saved = frappe.get_doc("Address", doc.name)
		self.assertEqual(saved.custom_area, "Al Olaya")
		self.assertEqual(saved.custom_building_number, "6823")
		self.assertEqual(saved.address_line1, "Prince Sultan Road")
		self.assertEqual(saved.pincode, "12345")
		# `before_insert` makes the Short Code the title — item 5.9, still true.
		self.assertEqual(saved.address_title, "RQAA2929")

	def test_the_print_helper_returns_that_district_for_the_saved_address(self):
		"""End of the chain: what a tax invoice would actually print."""
		from yht_custom.print_helpers import yht_national_address

		values = self._parsed()
		doc = frappe.get_doc(
			dict(doctype="Address", address_type="Billing", country="Saudi Arabia", **values)
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Address", doc.name, force=1, ignore_permissions=True)

		out = yht_national_address(frappe._dict(customer_address=doc.name))
		self.assertEqual(out["district"], "Al Olaya")
		self.assertEqual(out["building"], "6823")
		self.assertEqual(out["street"], "Prince Sultan Road")
