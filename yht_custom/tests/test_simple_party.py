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
