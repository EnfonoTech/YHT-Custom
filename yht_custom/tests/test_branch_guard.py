# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Tests for the server-side branch scope guard and its Property Setters.

The guard is the boundary that makes `setup_property_setters` safe, so these
tests matter more than most: if the guard silently stops firing, branch
isolation on write is gone and nothing else would notice.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom.branch_guard import get_branch_scope, validate_branch_scope
from yht_custom.setup_property_setters import (
	IGNORE_USER_PERMISSION_FIELDS,
	setup_ignore_user_permissions,
)

TEST_BRANCH = "_Test YHT Guard Branch"
TEST_USER = "_test_yht_guard_user@example.com"


class TestPropertySetters(FrappeTestCase):
	def test_every_listed_field_actually_exists(self):
		"""A renamed or dropped ERPNext field would silently lose its setter."""
		missing = []
		for doctype, fieldname in IGNORE_USER_PERMISSION_FIELDS:
			if not frappe.db.exists("DocType", doctype):
				missing.append(f"{doctype} (doctype)")
				continue
			if not frappe.get_meta(doctype).get_field(fieldname):
				missing.append(f"{doctype}.{fieldname}")
		self.assertEqual(missing, [], f"fields in the list that do not exist: {missing}")

	def test_setters_are_applied(self):
		setup_ignore_user_permissions()
		frappe.db.commit()
		for doctype, fieldname in IGNORE_USER_PERMISSION_FIELDS:
			if not frappe.db.exists("DocType", doctype):
				continue
			if not frappe.get_meta(doctype).get_field(fieldname):
				continue
			value = frappe.db.get_value(
				"Property Setter",
				{"doc_type": doctype, "field_name": fieldname, "property": "ignore_user_permissions"},
				"value",
			)
			self.assertEqual(str(value), "1", f"{doctype}.{fieldname} has no ignore_user_permissions setter")

	def test_rerunning_creates_no_duplicates(self):
		"""after_migrate runs this every deploy; make_property_setter always inserts."""
		setup_ignore_user_permissions()
		setup_ignore_user_permissions()
		frappe.db.commit()
		dupes = frappe.db.sql(
			"""select doc_type, field_name, count(*) c from `tabProperty Setter`
			   where property = 'ignore_user_permissions'
			   group by doc_type, field_name having c > 1"""
		)
		self.assertEqual(dupes, (), f"duplicate Property Setters: {dupes}")


class TestBranchGuard(FrappeTestCase):
	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		if not self.company:
			self.skipTest("no Company on this site")

		warehouses = frappe.get_all(
			"Warehouse", filters={"company": self.company, "is_group": 0}, pluck="name", limit=2
		)
		if len(warehouses) < 2:
			self.skipTest("need two leaf warehouses to test in-scope vs out-of-scope")
		self.mine, self.theirs = warehouses[0], warehouses[1]

		self.cost_center = frappe.get_all(
			"Cost Center", filters={"company": self.company, "is_group": 0}, pluck="name", limit=1
		)[0]

		if not frappe.db.exists("Branch", TEST_BRANCH):
			frappe.get_doc({"doctype": "Branch", "branch": TEST_BRANCH}).insert(ignore_permissions=True)
		if not frappe.db.exists("User", TEST_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": TEST_USER,
					"first_name": "Test Guard",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

		if frappe.db.exists("Branch Configuration", TEST_BRANCH):
			frappe.delete_doc("Branch Configuration", TEST_BRANCH, force=1, ignore_permissions=True)
		cfg = frappe.new_doc("Branch Configuration")
		cfg.branch = TEST_BRANCH
		cfg.company = self.company
		cfg.append("warehouse", {"warehouse": self.mine})
		cfg.append("cost_center", {"cost_center": self.cost_center})
		cfg.append("user", {"user": TEST_USER, "role": "Branch User"})
		cfg.insert(ignore_permissions=True)

		frappe.clear_cache(user=TEST_USER)
		# the per-request cache in branch_defaults must not leak between tests
		if hasattr(frappe.local, "yht_branch_config_cache"):
			delattr(frappe.local, "yht_branch_config_cache")

	def tearDown(self):
		frappe.set_user("Administrator")
		if hasattr(frappe.local, "yht_branch_config_cache"):
			delattr(frappe.local, "yht_branch_config_cache")
		frappe.db.rollback()

	def _stub(self, warehouse=None, cost_center=None, item_warehouse=None):
		"""A Delivery Note shaped doc, not inserted — the guard runs on validate."""
		doc = frappe.new_doc("Delivery Note")
		doc.company = self.company
		if warehouse:
			doc.set_warehouse = warehouse
		if cost_center:
			doc.cost_center = cost_center
		doc.append(
			"items",
			{
				"item_code": frappe.db.get_value("Item", {"is_stock_item": 1}, "name"),
				"qty": 1,
				"warehouse": item_warehouse or warehouse or self.mine,
			},
		)
		return doc

	def test_scope_reports_the_branch_warehouse(self):
		frappe.set_user(TEST_USER)
		scope = get_branch_scope()
		self.assertTrue(scope["restricted"])
		self.assertIn(self.mine, scope["warehouses"])
		self.assertNotIn(self.theirs, scope["warehouses"])

	def test_in_scope_warehouse_passes(self):
		frappe.set_user(TEST_USER)
		validate_branch_scope(self._stub(warehouse=self.mine))  # must not raise

	def test_out_of_scope_header_warehouse_is_rejected(self):
		frappe.set_user(TEST_USER)
		doc = self._stub(warehouse=self.theirs)
		self.assertRaises(frappe.ValidationError, validate_branch_scope, doc)

	def test_out_of_scope_item_warehouse_is_rejected(self):
		"""The item row is what reaches the stock ledger — it must be checked too."""
		frappe.set_user(TEST_USER)
		doc = self._stub(warehouse=self.mine, item_warehouse=self.theirs)
		self.assertRaises(frappe.ValidationError, validate_branch_scope, doc)

	def test_administrator_is_not_restricted(self):
		frappe.set_user("Administrator")
		validate_branch_scope(self._stub(warehouse=self.theirs))  # must not raise

	def test_unmapped_user_is_not_restricted(self):
		"""Someone with no Branch Configuration falls back to standard permissions."""
		frappe.set_user("Administrator")
		scope = get_branch_scope()
		self.assertFalse(scope["restricted"])

	def test_company_default_cost_center_is_always_in_scope(self):
		"""ERPNext tax templates hardcode it; excluding it fails every taxed doc."""
		default_cc = frappe.db.get_value("Company", self.company, "cost_center")
		if not default_cc:
			self.skipTest("company has no default cost center")
		frappe.set_user(TEST_USER)
		self.assertIn(default_cc, get_branch_scope()["cost_centers"])
