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
