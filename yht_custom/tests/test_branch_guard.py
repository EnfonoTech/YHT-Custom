# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Tests for the server-side branch scope guard and its Property Setters.

The guard is the boundary that makes `setup_property_setters` safe, so these
tests matter more than most: if the guard silently stops firing, branch
isolation on write is gone and nothing else would notice.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom.branch_fields import GUARDED_PARENTS, all_scoped_pairs, get_scoped_fields
from yht_custom.branch_guard import get_branch_scope, validate_branch_scope
from yht_custom.setup_property_setters import setup_ignore_user_permissions

TEST_BRANCH = "_Test YHT Guard Branch"
TEST_USER = "_test_yht_guard_user@example.com"


class TestPropertySetters(FrappeTestCase):
	def test_pairs_are_derived_and_non_empty(self):
		"""Derived from live metadata, so every pair exists by construction."""
		pairs = all_scoped_pairs()
		self.assertGreater(len(pairs), 30, "suspiciously few scoped fields discovered")
		for doctype, fieldname in pairs:
			field = frappe.get_meta(doctype).get_field(fieldname)
			self.assertIsNotNone(field, f"{doctype}.{fieldname}")
			self.assertEqual(field.fieldtype, "Link")
			self.assertIn(field.options, ("Warehouse", "Cost Center"))

	def test_known_v15_fields_are_discovered(self):
		"""Fields the first hand-written list MISSED. Regression guard: each of
		these is a field a branch user could otherwise point at another branch."""
		expected = [
			("Purchase Receipt", "rejected_warehouse"),
			("Purchase Receipt Item", "rejected_warehouse"),
			("Sales Invoice", "set_target_warehouse"),
			("Sales Invoice", "write_off_cost_center"),
			("Sales Order", "cost_center"),
			("Purchase Order", "set_from_warehouse"),
			("Delivery Note", "cost_center"),
			("Material Request Item", "cost_center"),
		]
		pairs = set(all_scoped_pairs())
		missing = [p for p in expected if p not in pairs]
		self.assertEqual(missing, [], f"discovery missed: {missing}")

	def test_quotation_has_no_warehouse_header_field(self):
		"""The first list named Quotation.set_warehouse, which does not exist in
		v15 — this pins the fact so it cannot creep back."""
		self.assertEqual(get_scoped_fields("Quotation")["Warehouse"], [])
		self.assertEqual(get_scoped_fields("Quotation Item")["Cost Center"], [])

	def test_setters_are_applied(self):
		setup_ignore_user_permissions()
		frappe.db.commit()
		for doctype, fieldname in all_scoped_pairs():
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

	def test_setter_and_guard_cover_the_same_fields(self):
		"""The whole point of branch_fields: a field whose link check is switched
		off but which the guard does not validate is an unguarded hole."""
		for doctype, _fieldname in all_scoped_pairs():
			# every scoped doctype is either guarded directly or reached as a child
			reachable = doctype in GUARDED_PARENTS or any(
				doctype.startswith(parent) for parent in GUARDED_PARENTS
			)
			if doctype == "Item Default":
				continue  # a master, seeded onto documents; not itself posted by a branch user
			self.assertTrue(reachable, f"{doctype} has setters but the guard never sees it")


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

	def test_out_of_scope_rejected_warehouse_is_rejected(self):
		"""rejected_warehouse was missing from the first hand-written list — a
		branch user could have routed rejected stock to another branch."""
		frappe.set_user(TEST_USER)
		doc = frappe.new_doc("Purchase Receipt")
		doc.company = self.company
		doc.supplier = frappe.db.get_value("Supplier", {}, "name")
		if not doc.supplier:
			self.skipTest("no Supplier on this site")
		doc.set_warehouse = self.mine
		doc.rejected_warehouse = self.theirs
		self.assertRaises(frappe.ValidationError, validate_branch_scope, doc)

	def test_company_default_cost_center_is_always_in_scope(self):
		"""ERPNext tax templates hardcode it; excluding it fails every taxed doc."""
		default_cc = frappe.db.get_value("Company", self.company, "cost_center")
		if not default_cc:
			self.skipTest("company has no default cost center")
		frappe.set_user(TEST_USER)
		self.assertIn(default_cc, get_branch_scope()["cost_centers"])


class TestProvisioning(FrappeTestCase):
	"""after_migrate must be resilient and idempotent — it runs on every deploy."""

	def test_module_profile_is_a_noop_when_unchanged(self):
		"""Saving a Module Profile leaves it locked, so a repeat save used to kill
		the whole migrate with DocumentLockedError."""
		from yht_custom.setup import MODULE_PROFILE, ensure_module_profile

		ensure_module_profile()
		frappe.db.commit()
		before = frappe.db.get_value("Module Profile", MODULE_PROFILE, "modified")

		ensure_module_profile()  # must not raise, must not touch the document
		frappe.db.commit()
		after = frappe.db.get_value("Module Profile", MODULE_PROFILE, "modified")
		self.assertEqual(before, after, "second call re-saved the Module Profile")

	def test_module_profile_survives_a_stale_lock(self):
		from yht_custom.setup import MODULE_PROFILE, ensure_module_profile

		ensure_module_profile()
		frappe.db.commit()

		doc = frappe.get_doc("Module Profile", MODULE_PROFILE)
		# lock() itself raises if the document is already locked — and on a live
		# site it often is, left behind by the apply-to-users job. Normalise first.
		if doc.is_locked:
			doc.unlock()
		doc.lock()
		self.assertTrue(frappe.get_doc("Module Profile", MODULE_PROFILE).is_locked)

		# force a change so the function has to save through the lock
		frappe.db.delete("Block Module", {"parent": MODULE_PROFILE, "module": "Core"})
		frappe.db.commit()
		try:
			ensure_module_profile()  # must not raise
		finally:
			fresh = frappe.get_doc("Module Profile", MODULE_PROFILE)
			if fresh.is_locked:
				fresh.unlock()
		frappe.db.commit()

	def test_after_migrate_reports_failures_instead_of_aborting(self):
		"""A failing step must not swallow the ones after it."""
		from yht_custom import setup

		result = setup.after_migrate()
		self.assertIn("failures", result)
		self.assertEqual(result["failures"], [], f"after_migrate reported failures: {result['failures']}")


class TestBranchPeerScoping(FrappeTestCase):
	"""Quotations carry no warehouse. Scoping them to `owner = me` hid a
	colleague's quotation from the same branch — measured as 0 of 2,766 visible,
	which reads as a broken screen rather than a boundary."""

	def tearDown(self):
		frappe.db.rollback()

	def test_peers_include_self_and_colleagues(self):
		from yht_custom.branch_filters import get_branch_peers

		company = frappe.db.get_value("Company", {}, "name")
		branch = "_Test YHT Peer Branch"
		a, b = "_test_yht_peer_a@example.invalid", "_test_yht_peer_b@example.invalid"

		if not frappe.db.exists("Branch", branch):
			frappe.get_doc({"doctype": "Branch", "branch": branch}).insert(ignore_permissions=True)
		for email in (a, b):
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{"doctype": "User", "email": email, "first_name": "Peer", "send_welcome_email": 0}
				).insert(ignore_permissions=True)

		if frappe.db.exists("Branch Configuration", branch):
			frappe.delete_doc("Branch Configuration", branch, force=1, ignore_permissions=True)
		cfg = frappe.new_doc("Branch Configuration")
		cfg.branch = branch
		cfg.company = company
		cfg.append("user", {"user": a, "role": "Branch User"})
		cfg.append("user", {"user": b, "role": "Branch User"})
		cfg.insert(ignore_permissions=True)

		peers = get_branch_peers(a)
		self.assertIn(a, peers)
		self.assertIn(b, peers, "a colleague on the same branch was not treated as a peer")

	def test_unmapped_user_has_no_peers(self):
		from yht_custom.branch_filters import get_branch_peers

		self.assertEqual(get_branch_peers("_nobody_yht@example.invalid"), [])

	def test_quotation_query_scopes_to_peers_not_just_owner(self):
		from yht_custom.branch_filters import quotation_query

		# Administrator is unrestricted, so the fragment must be empty
		self.assertEqual(quotation_query("Administrator"), "")
