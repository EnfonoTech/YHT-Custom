# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Simple Customer / Supplier creation (plan 5.10).

These tests WRITE. FrappeTestCase wraps each in a transaction and rolls it back,
which is the only reason that is acceptable on a live client site — `bench
execute` would commit, and once left a real submitted invoice behind.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom.api import party

BRANCH_USER = "branchtest@yht-khobhar.enfonoerp.com"


class TestCreateParty(FrappeTestCase):
	def setUp(self):
		self.name = "_Test YHT Quick Party"

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _address(self, **overrides):
		return {
			"address_line1": "King Fahd Road",
			"custom_building_number": "1234",
			"custom_area": "Al Aqrabiyah",
			"custom_additional_number": "5678",
			"city": "Al Khobar",
			"pincode": "34421",
			"country": "Saudi Arabia",
			**overrides,
		}

	def test_a_customer_arrives_with_its_address_and_contact(self):
		"""One call, three documents. The address is the point of the exercise."""
		result = party.create_party(
			doctype="Customer",
			party_name=self.name,
			tax_id="311264592800003",
			mobile="0500000000",
			email="quick@example.com",
			address=self._address(),
		)

		self.assertTrue(result["name"])
		self.assertTrue(result["address"])
		self.assertTrue(result["contact"])

		address = frappe.get_doc("Address", result["address"])
		self.assertEqual(address.custom_area, "Al Aqrabiyah")
		self.assertEqual(address.custom_building_number, "1234")
		self.assertEqual(address.links[0].link_doctype, "Customer")
		self.assertEqual(address.links[0].link_name, result["name"])

	def test_the_national_address_rules_are_not_bypassed(self):
		"""The dialog is not a way around saudi_address.validate."""
		with self.assertRaises(frappe.ValidationError):
			party.create_party(
				doctype="Customer",
				party_name=self.name,
				address=self._address(pincode="00"),
			)

	def test_a_short_code_becomes_the_address_title(self):
		result = party.create_party(
			doctype="Customer",
			party_name=self.name,
			address=self._address(custom_short_address="rqaa2929"),
		)
		address = frappe.get_doc("Address", result["address"])
		self.assertEqual(address.address_title, "RQAA2929")

	def test_no_address_details_creates_no_address(self):
		"""An empty address is not an error, and not a blank record either."""
		result = party.create_party(doctype="Customer", party_name=self.name, address={})
		self.assertTrue(result["name"])
		self.assertIsNone(result["address"])

	def test_no_contact_details_creates_no_contact(self):
		result = party.create_party(
			doctype="Customer", party_name=self.name, address=self._address()
		)
		self.assertIsNone(result["contact"])

	def test_a_blank_name_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			party.create_party(doctype="Customer", party_name="   ")

	def test_an_unsupported_doctype_is_refused(self):
		"""Every @frappe.whitelist() is a public HTTP endpoint."""
		with self.assertRaises(frappe.ValidationError):
			party.create_party(doctype="Item", party_name=self.name)
		with self.assertRaises(frappe.ValidationError):
			party.get_party_defaults(doctype="User")

	def test_a_json_string_address_is_accepted(self):
		"""frappe.call sends a dict as a JSON string over HTTP."""
		result = party.create_party(
			doctype="Customer",
			party_name=self.name,
			address=frappe.as_json(self._address()),
		)
		self.assertTrue(result["address"])


class TestPartyPermissions(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _as_branch_user(self):
		if not frappe.db.exists("User", BRANCH_USER):
			self.skipTest("no branch user on this site")
		# A role granted moments ago is not in the cached permission set.
		frappe.clear_cache(user=BRANCH_USER)
		frappe.set_user(BRANCH_USER)

	def test_a_branch_user_may_create_a_customer(self):
		self._as_branch_user()
		self.assertTrue(party.get_party_defaults("Customer")["can_create"])

	def test_a_branch_user_may_not_create_a_supplier(self):
		"""Branch User holds read on Supplier and nothing more, by design.

		The dialog hides the button, but the button is not the boundary — this is.
		"""
		self._as_branch_user()
		self.assertFalse(party.get_party_defaults("Supplier")["can_create"])
		with self.assertRaises(frappe.PermissionError):
			party.create_party(doctype="Supplier", party_name="_Test YHT Blocked Supplier")

	def test_nothing_is_created_with_ignore_permissions(self):
		"""A refused call must leave no trace."""
		self._as_branch_user()
		before = frappe.db.count("Supplier")
		try:
			party.create_party(doctype="Supplier", party_name="_Test YHT Blocked Supplier")
		except frappe.PermissionError:
			pass
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("Supplier"), before)


class TestPartyDefaults(FrappeTestCase):
	def test_the_default_group_is_never_a_group_node(self):
		"""Selling Settings.customer_group is `All Customer Groups` on this site.

		Customer.validate_customer_group throws on a group node, so reading the
		setting straight through made every quick-created customer fail. ERPNext's
		own quick entry has the same problem here.
		"""
		for doctype in ("Customer", "Supplier"):
			with self.subTest(doctype=doctype):
				group = party.default_group(doctype)
				self.assertTrue(group, f"no usable {doctype} Group")
				self.assertFalse(
					frappe.db.get_value(f"{doctype} Group", group, "is_group"),
					f"{group} is a group node and cannot be assigned",
				)

	def test_the_default_group_follows_actual_usage(self):
		"""427 of 428 customers are Commercial. That is the right default."""
		most_used = frappe.db.get_all(
			"Customer",
			filters={"customer_group": ["is", "set"]},
			fields=["customer_group", "count(name) as total"],
			group_by="customer_group",
			order_by="total desc",
			limit=2,
		)
		leaves = [
			row.customer_group
			for row in most_used
			if not frappe.db.get_value("Customer Group", row.customer_group, "is_group")
		]
		if leaves:
			self.assertEqual(party.default_group("Customer"), leaves[0])

	def test_the_default_territory_is_never_a_group_node(self):
		territory = party.default_territory()
		if territory:
			self.assertFalse(frappe.db.get_value("Territory", territory, "is_group"))


class TestPartyModes(FrappeTestCase):
	"""🔴 B2B/B2C, and the field ZATCA actually reads.

	`ksa_compliance.is_b2b_customer` tests `custom_vat_registration_number`, NOT the
	core `tax_id`. Before this, the dialog wrote `tax_id` only — so a VAT-registered
	buyer created through it was invoiced as SIMPLIFIED with no buyer VAT, and the
	XML submitted to ZATCA said the same. Measured on this site the day it was
	found: 14 of 435 customers carried a VAT number in `tax_id` alone.

	So the mode is not cosmetic. B2B writes both fields and insists on the national
	address a standard invoice cannot clear without; B2C asks for neither.
	"""

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _address(self, **overrides):
		return {
			"address_line1": "King Fahd Road",
			"custom_building_number": "1234",
			"custom_area": "Al Aqrabiyah",
			"city": "Al Khobar",
			"pincode": "34421",
			"country": "Saudi Arabia",
			**overrides,
		}

	def test_a_b2b_customer_carries_the_vat_number_zatca_reads(self):
		out = party.create_party(
			doctype="Customer",
			mode="B2B",
			party_name="_Test YHT B2B Customer",
			tax_id="311111111100003",
			address=self._address(),
		)
		doc = frappe.get_doc("Customer", out["name"])
		self.assertEqual(doc.customer_type, "Company")
		self.assertEqual(doc.tax_id, "311111111100003")
		if doc.meta.has_field("custom_vat_registration_number"):
			self.assertEqual(
				doc.custom_vat_registration_number,
				"311111111100003",
				"the field ksa_compliance reads was left empty — the invoice would clear as simplified",
			)

	def test_a_b2c_customer_is_an_individual_and_needs_nothing_else(self):
		out = party.create_party(
			doctype="Customer", mode="B2C", party_name="_Test YHT B2C Customer"
		)
		doc = frappe.get_doc("Customer", out["name"])
		self.assertEqual(doc.customer_type, "Individual")
		self.assertFalse(doc.tax_id)
		if doc.meta.has_field("custom_vat_registration_number"):
			self.assertFalse(doc.custom_vat_registration_number)

	def test_a_b2b_customer_without_a_vat_number_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			party.create_party(
				doctype="Customer",
				mode="B2B",
				party_name="_Test YHT B2B No VAT",
				address=self._address(),
			)

	def test_a_b2b_customer_without_a_district_is_refused(self):
		"""The district is the one every address on this site was missing."""
		with self.assertRaises(frappe.ValidationError):
			party.create_party(
				doctype="Customer",
				mode="B2B",
				party_name="_Test YHT B2B No District",
				tax_id="311111111100003",
				address=self._address(custom_area=""),
			)

	def test_the_address_rule_does_not_apply_to_a_supplier(self):
		"""ZATCA constrains the BUYER. A supplier is just a company with a tax id."""
		out = party.create_party(
			doctype="Supplier",
			mode="B2B",
			party_name="_Test YHT B2B Supplier",
			tax_id="311111111100003",
		)
		doc = frappe.get_doc("Supplier", out["name"])
		self.assertEqual(doc.tax_id, "311111111100003")
		if doc.meta.has_field("supplier_type"):
			self.assertEqual(doc.supplier_type, "Company")

	def test_a_b2c_supplier_is_an_individual(self):
		out = party.create_party(
			doctype="Supplier", mode="B2C", party_name="_Test YHT B2C Supplier"
		)
		doc = frappe.get_doc("Supplier", out["name"])
		if doc.meta.has_field("supplier_type"):
			self.assertEqual(doc.supplier_type, "Individual")

	def test_an_unknown_mode_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			party.create_party(doctype="Customer", mode="B2X", party_name="_Test YHT Bad Mode")

	def test_a_missing_mode_is_inferred_from_the_vat_number(self):
		"""🔴 Defaulting to B2B broke four existing callers that pass no VAT.

		They are legitimate — a short-code address, no address, no contact — and had
		no way to satisfy a requirement invented after they were written. So a missing
		mode is inferred, and only a DECLARED B2B is held to the address promise.
		"""
		self.assertEqual(party._normalise_mode(None), ("B2C", False))
		self.assertEqual(party._normalise_mode("", ""), ("B2C", False))
		self.assertEqual(party._normalise_mode(None, "311111111100003"), ("B2B", False))
		self.assertEqual(party._normalise_mode("b2c"), ("B2C", True))
		self.assertEqual(party._normalise_mode("B2B"), ("B2B", True))

	def test_an_inferred_b2b_still_routes_the_vat_to_the_zatca_field(self):
		"""The inference is not a loophole — it fixes the bug for old callers too."""
		out = party.create_party(
			doctype="Customer",
			party_name="_Test YHT Inferred B2B",
			tax_id="311111111100003",
			address=self._address(custom_area=""),   # incomplete, and NOT refused
		)
		doc = frappe.get_doc("Customer", out["name"])
		if doc.meta.has_field("custom_vat_registration_number"):
			self.assertEqual(doc.custom_vat_registration_number, "311111111100003")

	def test_the_dialog_is_told_which_modes_exist(self):
		d = party.get_party_defaults("Customer")
		self.assertEqual(d["modes"], ["B2B", "B2C"])
		self.assertEqual(d["default_mode"], "B2B")
		self.assertIn("custom_area", d["b2b_address_required"])
