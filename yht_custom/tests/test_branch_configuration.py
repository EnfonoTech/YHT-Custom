# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Tests for Branch Configuration provisioning and branch list filtering.

Run: bench --site yht-khobhar.enfonoerp.com run-tests --app yht_custom
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom.branch_filters import get_branch_warehouses

TEST_BRANCH = "_Test YHT Branch"
TEST_USER = "_test_yht_branch_user@example.com"


class TestBranchConfiguration(FrappeTestCase):
	# Fixtures are built in setUp, NOT setUpClass: FrappeTestCase wraps each test
	# in a transaction and tearDown rolls it back, which would take class-level
	# inserts with it and leave every test after the first without its Branch.
	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		if not self.company:
			self.skipTest("no Company on this site")

		self.warehouses = frappe.get_all(
			"Warehouse", filters={"company": self.company, "is_group": 0}, pluck="name", limit=2
		)
		self.cost_centers = frappe.get_all(
			"Cost Center", filters={"company": self.company, "is_group": 0}, pluck="name", limit=1
		)
		if not self.warehouses or not self.cost_centers:
			self.skipTest("need at least one leaf Warehouse and Cost Center")

		if not frappe.db.exists("Branch", TEST_BRANCH):
			frappe.get_doc({"doctype": "Branch", "branch": TEST_BRANCH}).insert(ignore_permissions=True)

		if not frappe.db.exists("User", TEST_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": TEST_USER,
					"first_name": "Test Branch",
					"send_welcome_email": 0,
					"user_type": "Website User",  # deliberately: exercises the upgrade path
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	def _make_config(self):
		if frappe.db.exists("Branch Configuration", TEST_BRANCH):
			frappe.delete_doc("Branch Configuration", TEST_BRANCH, force=1, ignore_permissions=True)

		doc = frappe.new_doc("Branch Configuration")
		doc.branch = TEST_BRANCH
		doc.company = self.company
		for wh in self.warehouses:
			doc.append("warehouse", {"warehouse": wh})
		doc.append("cost_center", {"cost_center": self.cost_centers[0]})
		doc.append("user", {"user": TEST_USER, "role": "Branch User"})
		doc.insert(ignore_permissions=True)
		return doc

	def test_autoname_is_the_branch(self):
		doc = self._make_config()
		self.assertEqual(doc.name, TEST_BRANCH)

	def test_website_user_is_upgraded_to_system_user(self):
		"""Website Users silently lose desk roles — the role assignment would no-op."""
		frappe.db.set_value("User", TEST_USER, "user_type", "Website User")
		self._make_config()
		self.assertEqual(frappe.db.get_value("User", TEST_USER, "user_type"), "System User")

	def test_role_is_assigned(self):
		self._make_config()
		self.assertTrue(frappe.db.exists("Has Role", {"parent": TEST_USER, "role": "Branch User"}))

	def test_user_permissions_are_provisioned(self):
		self._make_config()
		for allow, value in (
			("Company", self.company),
			("Branch", TEST_BRANCH),
			("Warehouse", self.warehouses[0]),
			("Cost Center", self.cost_centers[0]),
		):
			self.assertTrue(
				frappe.db.exists("User Permission", {"user": TEST_USER, "allow": allow, "for_value": value}),
				f"missing User Permission {allow}={value}",
			)

	def test_first_warehouse_row_becomes_the_default(self):
		self._make_config()
		default = frappe.db.get_value(
			"User Permission", {"user": TEST_USER, "allow": "Warehouse", "is_default": 1}, "for_value"
		)
		self.assertEqual(default, self.warehouses[0])

	def test_only_one_default_per_allow_type(self):
		"""Frappe permits exactly one default per (user, allow) — two would break login."""
		self._make_config()
		for allow in ("Company", "Warehouse", "Cost Center"):
			count = frappe.db.count("User Permission", {"user": TEST_USER, "allow": allow, "is_default": 1})
			self.assertLessEqual(count, 1, f"more than one default {allow} permission")

	def test_mismatched_company_is_rejected(self):
		"""A cost center from another company must fail loudly here, not at posting."""
		other = frappe.get_all(
			"Cost Center", filters={"company": ["!=", self.company], "is_group": 0}, pluck="name", limit=1
		)
		if not other:
			self.skipTest("single-company site — no cross-company cost center to test with")

		doc = frappe.new_doc("Branch Configuration")
		doc.branch = TEST_BRANCH
		doc.company = self.company
		doc.append("cost_center", {"cost_center": other[0]})
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_unassignable_role_is_rejected(self):
		doc = frappe.new_doc("Branch Configuration")
		doc.branch = TEST_BRANCH
		doc.company = self.company
		doc.append("user", {"user": TEST_USER, "role": "System Manager"})
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_duplicate_user_row_is_rejected(self):
		doc = frappe.new_doc("Branch Configuration")
		doc.branch = TEST_BRANCH
		doc.company = self.company
		doc.append("user", {"user": TEST_USER, "role": "Branch User"})
		doc.append("user", {"user": TEST_USER, "role": "Branch User"})
		self.assertRaises(frappe.ValidationError, doc.insert)


class TestBranchFilters(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_administrator_is_unrestricted(self):
		self.assertEqual(get_branch_warehouses("Administrator"), [])

	def test_unmapped_user_is_unrestricted(self):
		"""No Branch Configuration means standard Frappe permissions govern."""
		self.assertEqual(get_branch_warehouses("_not_a_branch_user@example.com"), [])

	def test_query_fragments_are_escaped(self):
		"""permission_query_conditions has no parameter binding — escaping is on us."""
		from yht_custom import branch_filters

		fragment = branch_filters._branch_peers_only("Quotation", "Administrator")
		self.assertEqual(fragment, "")


class TestNamingSeriesOptionsMerge(FrappeTestCase):
	"""setup_branch_series must not delete series other steps registered.

	It used to rebuild the options list from `standard + branch templates`, which
	silently removed the expense series every time it ran.
	"""

	def tearDown(self):
		frappe.db.rollback()

	def test_existing_entries_survive_a_reseed(self):
		from yht_custom.setup_branch_series import setup_branch_series

		# 🔴 NEVER frappe.db.commit() HERE. The first version did, and tearDown's
		# rollback cannot undo a committed write — so the marker became a PERMANENT
		# entry in the real Purchase Invoice naming-series picker on every site the
		# suite had ever run against, offered to operators as a choosable series. The
		# old marker `_TEST-KEEPME-` is listed in RETIRED_SERIES to clean it up.
		# The commit was never needed: setup_branch_series reads through frappe.db in
		# this same transaction and sees the uncommitted write.
		marker = "_TEST-SURVIVES-.YY.-.####"
		row = frappe.db.get_value(
			"Property Setter",
			{"doc_type": "Purchase Invoice", "field_name": "naming_series", "property": "options"},
			["name", "value"],
			as_dict=True,
		)
		if not row:
			self.skipTest("no naming_series Property Setter on Purchase Invoice yet")

		try:
			frappe.db.set_value("Property Setter", row.name, "value", (row.value or "") + "\n" + marker)
			setup_branch_series()
			after = frappe.db.get_value("Property Setter", row.name, "value") or ""
			self.assertIn(marker, after.split("\n"), "reseeding deleted an unrelated series")
		finally:
			frappe.db.set_value("Property Setter", row.name, "value", row.value)

	def test_expense_series_is_present_after_reseed(self):
		from yht_custom.expense_invoice import EXPENSE_SERIES, setup_expense_invoice
		from yht_custom.setup_branch_series import setup_branch_series

		setup_expense_invoice()
		setup_branch_series()
		frappe.db.commit()
		options = frappe.db.get_value(
			"Property Setter",
			{"doc_type": "Purchase Invoice", "field_name": "naming_series", "property": "options"},
			"value",
		) or ""
		self.assertIn(EXPENSE_SERIES, options.split("\n"))
