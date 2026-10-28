# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Inter Branch Sale (2026-10-19, HELD on `feature/inter-branch-sale`).

    bench --site yht-test run-tests --app yht_custom --skip-before-tests \
        --module yht_custom.tests.test_inter_branch_sale

`TestPosting` and `TestStructure` need no site data; `TestEndToEnd` builds its own accounts inside the test's
transaction (nothing commits) and skips when the site has no company / stock to sell.
"""

import json
import os
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, nowdate

from yht_custom import features
from yht_custom.tests.test_meeting_1011_wednesday import _off
from yht_custom.yht_custom.doctype.inter_branch_sale import inter_branch_sale as ibs
from yht_custom.yht_custom.doctype.inter_branch_sale_settings import inter_branch_sale_settings as st

DOCTYPE_DIR = os.path.join(os.path.dirname(ibs.__file__), "..")


def _json(name):
	with open(os.path.join(DOCTYPE_DIR, name, name + ".json")) as f:
		return json.load(f)


class TestPosting(FrappeTestCase):
	"""The Journal Entry is the sale side of a Sales Invoice: receivable and income, both at the selling price."""

	def test_receivable_and_income_at_the_selling_price(self):
		self.assertEqual(ibs.posting_rows(150), [("receivable", 150.0, 0.0), ("income", 0.0, 150.0)])

	def test_no_clearing_or_margin_leg(self):
		self.assertEqual([leg for leg, _d, _c in ibs.posting_rows(80)], ["receivable", "income"])

	def test_the_entry_always_balances(self):
		for amount in (150, 80, 33.335, 0.01, 1234567.89):
			rows = ibs.posting_rows(amount)
			with self.subTest(amount=amount):
				self.assertAlmostEqual(sum(d for _l, d, _c in rows), sum(c for _l, _d, c in rows), places=2)


class TestStructure(FrappeTestCase):
	def test_the_switch_is_known(self):
		self.assertIn(ibs.FEATURE, features.KNOWN)
		features.enabled(ibs.FEATURE)

	def test_the_four_doctypes_exist_in_the_module(self):
		for name, kind in (
			("inter_branch_sale", "submittable"),
			("inter_branch_sale_item", "table"),
			("inter_branch_sale_customer", "table"),
			("inter_branch_sale_settings", "single"),
		):
			doc = _json(name)
			with self.subTest(doctype=name):
				self.assertEqual(doc["module"], "Yht Custom")
				if kind == "submittable":
					self.assertEqual(doc["is_submittable"], 1)
				elif kind == "table":
					self.assertEqual(doc["istable"], 1)
				else:
					self.assertEqual(doc["issingle"], 1)

	def test_every_field_the_controller_writes_is_declared(self):
		doc = {f["fieldname"] for f in _json("inter_branch_sale")["fields"]}
		item = {f["fieldname"] for f in _json("inter_branch_sale_item")["fields"]}
		for field in ("stock_entry", "journal_entry", "total_qty", "total_amount", "total_cost", "margin", "status", "customer_name", "from_warehouse", "price_list", "cost_center", "items", "naming_series"):
			self.assertIn(field, doc, field)
		for field in ("item_code", "qty", "uom", "conversion_factor", "rate", "amount", "valuation_rate", "cost_amount", "warehouse"):
			self.assertIn(field, item, field)

	def test_field_order_matches_the_fields(self):
		for name in ("inter_branch_sale", "inter_branch_sale_item", "inter_branch_sale_settings"):
			doc = _json(name)
			with self.subTest(doctype=name):
				self.assertEqual(sorted(doc["field_order"]), sorted(f["fieldname"] for f in doc["fields"]))

	def test_the_settings_name_every_account_the_posting_uses(self):
		fields = {f["fieldname"] for f in _json("inter_branch_sale_settings")["fields"]}
		for field in st.REQUIRED:
			self.assertIn(field, fields)

	def test_the_series_abbreviation_is_new(self):
		options = {f["fieldname"]: f for f in _json("inter_branch_sale")["fields"]}["naming_series"]["options"]
		self.assertEqual(options, "KSIB-.YY.-.####")
		from yht_custom import setup_branch_series as sbs

		known = " ".join(str(v) for v in vars(sbs).values() if isinstance(v, (dict, list, tuple, str)))
		self.assertNotIn("KSIB", known)

	def test_it_cannot_be_deleted_by_a_branch_role_and_is_not_open_to_everyone(self):
		roles = {p["role"] for p in _json("inter_branch_sale")["permissions"]}
		self.assertTrue(roles <= {"Stock Manager", "Sales Manager", "Accounts Manager", "System Manager"})
		deleters = {p["role"] for p in _json("inter_branch_sale")["permissions"] if p.get("delete")}
		self.assertEqual(deleters, {"System Manager"})

	def test_the_script_calls_methods_that_are_whitelisted(self):
		for fn in (ibs.get_item_rates, ibs.get_inter_branch_customers, ibs.get_defaults):
			self.assertIn(fn, frappe.whitelisted)
		with open(os.path.join(DOCTYPE_DIR, "inter_branch_sale", "inter_branch_sale.js")) as f:
			source = f.read()
		for name in ("get_item_rates", "get_inter_branch_customers", "get_defaults"):
			self.assertIn("inter_branch_sale." + name, source)

	def test_a_sale_waits_for_its_switch(self):
		doc = frappe.new_doc("Inter Branch Sale")
		with _off(ibs.FEATURE), self.assertRaises(frappe.ValidationError):
			doc.validate()


class TestSettingsGaps(FrappeTestCase):
	def _settings(self, **kw):
		base = {"company": "C", "receivable_account": "R", "cogs_account": "K", "income_account": "M", "cost_center": "CC", "customers": [frappe._dict(customer="CU1")]}
		base.update(kw)
		return frappe._dict(base)

	def test_a_complete_setup_has_no_gaps(self):
		self.assertEqual(st.gaps(self._settings()), [])

	def test_each_missing_account_is_named(self):
		for field, label in st.REQUIRED.items():
			with self.subTest(field=field):
				self.assertIn(label, st.gaps(self._settings(**{field: ""})))

	def test_no_customer_is_a_gap(self):
		self.assertIn("Inter-Branch Customers", st.gaps(self._settings(customers=[])))

	def test_the_sale_refuses_to_submit_while_a_gap_is_open(self):
		doc = frappe.new_doc("Inter Branch Sale")
		doc.company = "C"
		with mock.patch.object(ibs, "_gaps", return_value=["Receivable Account"]), mock.patch.object(features, "enabled", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				doc.before_submit()


def _make_fixtures(self):
	"""Accounts, settings and a customer, built inside the test's transaction. Shared by both end-to-end classes."""
	self.company = frappe.db.get_value("Company", {}, "name")
	if not self.company or not frappe.get_cached_value("Company", self.company, "enable_perpetual_inventory"):
		self.skipTest("no company with perpetual inventory on this site")
	bins = frappe.get_all("Bin", filters={"actual_qty": [">", 5], "valuation_rate": [">", 0]}, fields=["item_code", "warehouse", "valuation_rate"], limit_page_length=1)
	if not bins:
		self.skipTest("no stock to sell on this site")
	self.bin = bins[0]
	self.customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
	if not self.customer:
		self.skipTest("no customer on this site")
	abbr = frappe.get_cached_value("Company", self.company, "abbr")
	self.accounts = {}
	for key, name, root, account_type, parent_type in (
		("receivable", "Test IB Receivable", "Asset", "Receivable", None),
		("cogs", "Test IB COGS", "Expense", "Cost of Goods Sold", None),
		("income", "Test IB Income", "Income", None, None),
	):
		existing = frappe.db.exists("Account", f"{name} - {abbr}")  # the class shares one transaction
		if existing:
			self.accounts[key] = existing
			continue
		parent = frappe.db.get_value("Account", {"company": self.company, "root_type": root, "is_group": 1}, "name")
		acc = frappe.get_doc({"doctype": "Account", "account_name": name, "company": self.company, "parent_account": parent, "root_type": root, "account_type": account_type or ""}).insert(ignore_permissions=True)
		self.accounts[key] = acc.name
	cc = frappe.db.get_value("Cost Center", {"company": self.company, "is_group": 0}, "name")
	settings = frappe.get_doc("Inter Branch Sale Settings")
	settings.update({"company": self.company, "receivable_account": self.accounts["receivable"], "cogs_account": self.accounts["cogs"], "income_account": self.accounts["income"], "cost_center": cc})
	settings.set("customers", [{"customer": self.customer}])
	settings.save(ignore_permissions=True)
	frappe.get_cached_doc("Inter Branch Sale Settings").reload()


class TestEndToEnd(FrappeTestCase):
	"""Real documents on a real site, inside the test's transaction."""

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		# The test saves the settings and reads them through the cache; the rollback does not clear a cached
		# document, so without this the site would keep serving the test's accounts.
		frappe.clear_document_cache("Inter Branch Sale Settings", "Inter Branch Sale Settings")

	def setUp(self):
		super().setUp()
		_make_fixtures(self)

	def _sale(self, qty=1, rate=None):
		rate = rate if rate is not None else flt(self.bin.valuation_rate) * 1.5
		doc = frappe.get_doc({
			"doctype": "Inter Branch Sale", "company": self.company, "customer": self.customer,
			"posting_date": nowdate(), "from_warehouse": self.bin.warehouse,
			"items": [{"item_code": self.bin.item_code, "qty": qty, "rate": rate}],
		})
		doc.insert(ignore_permissions=True)
		return doc

	def test_submit_posts_a_stock_entry_and_a_balanced_journal_entry(self):
		with mock.patch.object(features, "enabled", return_value=True):
			doc = self._sale()
			doc.submit()
		doc.reload()
		self.assertTrue(doc.stock_entry and doc.journal_entry)
		je = frappe.get_doc("Journal Entry", doc.journal_entry)
		self.assertEqual(je.docstatus, 1)
		self.assertAlmostEqual(je.total_debit, je.total_credit, places=2)
		receivable = next(a for a in je.accounts if a.account == self.accounts["receivable"])
		self.assertEqual(receivable.party, self.customer)
		self.assertAlmostEqual(receivable.debit_in_account_currency, doc.total_amount, places=2)
		income = next(a for a in je.accounts if a.account == self.accounts["income"])
		self.assertAlmostEqual(income.credit_in_account_currency, doc.total_amount, places=2)
		# The cost side is the Stock Entry's, as on a Sales Invoice with Update Stock: Dr COGS at the ledger cost.
		cogs = frappe.db.sql(
			"select sum(debit)-sum(credit) from `tabGL Entry` where voucher_no=%s and account=%s and is_cancelled=0",
			(doc.stock_entry, self.accounts["cogs"]),
		)[0][0]
		self.assertAlmostEqual(flt(cogs), doc.total_cost, places=2)
		self.assertAlmostEqual(doc.margin, flt(doc.total_amount - doc.total_cost, 2), places=2)

	def test_the_cost_of_goods_account_must_be_an_expense_account(self):
		settings = frappe.get_doc("Inter Branch Sale Settings")
		settings.cogs_account = self.accounts["income"]
		with self.assertRaises(frappe.ValidationError):
			settings.save(ignore_permissions=True)

	def test_cancel_reverses_both_documents(self):
		with mock.patch.object(features, "enabled", return_value=True):
			doc = self._sale()
			doc.submit()
			doc.reload()
			se, je = doc.stock_entry, doc.journal_entry
			doc.cancel()
		self.assertEqual(frappe.db.get_value("Stock Entry", se, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Journal Entry", je, "docstatus"), 2)

	def test_a_customer_outside_the_list_is_refused(self):
		other = frappe.db.get_value("Customer", {"name": ["!=", self.customer], "disabled": 0}, "name")
		if not other:
			self.skipTest("only one customer on this site")
		with mock.patch.object(features, "enabled", return_value=True):
			doc = self._sale()
			doc.customer = other
			with self.assertRaises(frappe.ValidationError):
				doc.save()

	def test_more_than_the_stock_is_refused(self):
		with mock.patch.object(features, "enabled", return_value=True):
			doc = self._sale(qty=flt(frappe.db.get_value("Bin", {"item_code": self.bin.item_code, "warehouse": self.bin.warehouse}, "actual_qty")) + 1)
			with self.assertRaises(frappe.ValidationError):
				doc.submit()


class TestBranchUserAccess(FrappeTestCase):
	"""2026-10-19 — "add this to the dashboard of branch users as well"."""

	def _source(self, path):
		from yht_custom.tests.test_meeting_1011_wednesday import _source

		return _source(path)

	def test_the_branch_roles_get_the_document_without_cancel(self):
		from yht_custom import setup as yht_setup

		spec = next(p for p in yht_setup.BRANCH_USER_PERMISSIONS if p["parent"] == "Inter Branch Sale")
		for field in ("read", "write", "create", "submit", "print"):
			self.assertEqual(spec[field], 1, field)
		self.assertFalse(spec.get("cancel"))
		self.assertFalse(spec.get("delete"))

	def test_the_list_and_the_guard_are_wired(self):
		from yht_custom.branch_fields import GUARDED_PARENTS, SCOPED_DOCTYPES

		self.assertEqual(GUARDED_PARENTS["Inter Branch Sale"], "items")
		self.assertIn("Inter Branch Sale Item", SCOPED_DOCTYPES)
		hooks = frappe.get_hooks("permission_query_conditions", app_name="yht_custom")
		self.assertIn("yht_custom.branch_filters.inter_branch_sale_query", hooks.get("Inter Branch Sale", []))
		events = frappe.get_hooks("doc_events", app_name="yht_custom")
		handlers = events.get("Inter Branch Sale", {}).get("validate")
		handlers = handlers if isinstance(handlers, list) else [handlers]
		self.assertIn("yht_custom.branch_guard.validate_branch_scope", handlers)

	def test_the_dashboard_tile_and_navigation_are_behind_the_switch(self):
		dash = self._source("yht_custom/page/yht_dashboard/yht_dashboard.js")
		restrict = self._source("public/js/branch_user_restrict.js")
		self.assertIn('doctype: "Inter Branch Sale"', dash)
		self.assertIn('feature: "oct19_inter_branch_sale"', dash)
		self.assertIn('"Inter Branch Sale",\n];', dash)  # the quick-create plus
		self.assertIn('ALLOWED_DOCTYPES.push("Inter Branch Sale")', restrict)
		self.assertIn("oct19_inter_branch_sale", restrict)

	def test_the_list_filter_is_the_warehouse_or_owner_shape(self):
		from yht_custom import branch_filters

		with mock.patch.object(branch_filters, "get_branch_warehouses", return_value=["Stores - KATC"]), mock.patch.object(
			branch_filters, "get_branch_peers", return_value=["a@x.com"]
		), mock.patch.object(branch_filters, "can_see_cancelled", return_value=False):
			clause = branch_filters.inter_branch_sale_query("a@x.com")
		self.assertIn("`tabInter Branch Sale`.`from_warehouse` IN ('Stores - KATC')", clause)
		self.assertIn("`tabInter Branch Sale Item` WHERE `warehouse` IN", clause)
		self.assertIn("`tabInter Branch Sale`.`owner` IN ('a@x.com')", clause)

	def test_an_unrestricted_user_gets_no_filter(self):
		from yht_custom import branch_filters

		with mock.patch.object(branch_filters, "get_branch_warehouses", return_value=[]):
			self.assertEqual(branch_filters.inter_branch_sale_query("Administrator"), "")


class TestBranchUserEndToEnd(FrappeTestCase):
	"""A real branch user raises and submits one, inside the test's transaction."""

	def setUp(self):
		super().setUp()
		from yht_custom import branch_filters
		from yht_custom import setup as yht_setup

		users = frappe.get_all("Has Role", filters={"role": "Branch User", "parenttype": "User"}, pluck="parent")
		self.user = next((u for u in users if frappe.db.get_value("User", u, "enabled") and branch_filters.get_branch_warehouses(u)), None)
		if not self.user:
			self.skipTest("no enabled Branch User with a mapped warehouse on this site")
		self.warehouses = branch_filters.get_branch_warehouses(self.user)
		self.company = frappe.db.get_value("Company", {}, "name")
		bins = frappe.get_all("Bin", filters={"warehouse": ["in", self.warehouses], "actual_qty": [">", 5], "valuation_rate": [">", 0]}, fields=["item_code", "warehouse", "valuation_rate"], limit_page_length=1)
		if not bins:
			self.skipTest("no stock in the branch user's warehouses")
		self.bin = bins[0]
		# the same two calls the site's after_migrate makes; rolled back with the test
		yht_setup.preserve_standard_docperms()
		yht_setup.setup_branch_user_permissions()
		frappe.clear_cache(doctype="Inter Branch Sale")
		_make_fixtures(self)  # accounts, settings and the customer, built the same way
		self.bin = bins[0]    # a bin the branch user is allowed to sell from

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		frappe.clear_document_cache("Inter Branch Sale Settings", "Inter Branch Sale Settings")

	def _sale(self, warehouse=None):
		doc = frappe.get_doc({
			"doctype": "Inter Branch Sale", "company": self.company, "customer": self.customer, "posting_date": nowdate(),
			"from_warehouse": warehouse or self.bin.warehouse,
			"items": [{"item_code": self.bin.item_code, "qty": 1, "rate": flt(self.bin.valuation_rate) * 1.5}],
		})
		return doc

	def test_a_branch_user_can_raise_and_submit_one(self):
		with mock.patch.object(features, "enabled", return_value=True):
			frappe.set_user(self.user)
			self.assertTrue(frappe.has_permission("Inter Branch Sale", "create"))
			doc = self._sale()
			doc.insert()
			doc.submit()
			frappe.set_user("Administrator")
			doc.reload()
		self.assertEqual(doc.docstatus, 1)
		self.assertTrue(doc.stock_entry and doc.journal_entry)

	def test_a_branch_user_cannot_cancel_it(self):
		with mock.patch.object(features, "enabled", return_value=True):
			frappe.set_user(self.user)
			self.assertFalse(frappe.has_permission("Inter Branch Sale", "cancel"))

	def test_selling_from_another_branchs_warehouse_is_refused(self):
		other = frappe.db.get_value("Warehouse", {"is_group": 0, "disabled": 0, "name": ["not in", self.warehouses], "company": self.company}, "name")
		if not other:
			self.skipTest("every warehouse on this site belongs to the branch user's branch")
		with mock.patch.object(features, "enabled", return_value=True):
			frappe.set_user(self.user)
			doc = self._sale(warehouse=other)
			with self.assertRaises(frappe.ValidationError):
				doc.insert()
