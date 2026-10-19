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
	def test_a_sale_above_cost_credits_the_margin(self):
		rows = ibs.posting_rows(150, 100)
		self.assertEqual(rows, [("receivable", 150.0, 0.0), ("clearing", 0.0, 100.0), ("margin", 0.0, 50.0)])

	def test_a_sale_below_cost_debits_the_margin(self):
		self.assertEqual(ibs.posting_rows(80, 100)[-1], ("margin", 20.0, 0.0))

	def test_a_sale_at_cost_has_no_margin_leg(self):
		self.assertEqual([leg for leg, _d, _c in ibs.posting_rows(100, 100)], ["receivable", "clearing"])

	def test_the_entry_always_balances(self):
		for amount, cost in ((150, 100), (80, 100), (100, 100), (33.335, 21.114), (0.01, 0.02), (1234567.89, 999999.99)):
			rows = ibs.posting_rows(amount, cost)
			with self.subTest(amount=amount, cost=cost):
				self.assertAlmostEqual(sum(d for _l, d, _c in rows), sum(c for _l, _d, c in rows), places=2)

	def test_the_receivable_is_the_selling_price_and_the_clearing_is_the_cost(self):
		rows = dict((leg, (d, c)) for leg, d, c in ibs.posting_rows(250.5, 200.25))
		self.assertEqual(rows["receivable"], (250.5, 0.0))
		self.assertEqual(rows["clearing"], (0.0, 200.25))


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
		base = {"company": "C", "receivable_account": "R", "clearing_account": "K", "margin_account": "M", "cost_center": "CC", "customers": [frappe._dict(customer="CU1")]}
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
			("clearing", "Test IB Clearing", "Asset", None, None),
			("margin", "Test IB Margin", "Income", None, None),
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
		settings.update({"company": self.company, "receivable_account": self.accounts["receivable"], "clearing_account": self.accounts["clearing"], "margin_account": self.accounts["margin"], "cost_center": cc})
		settings.set("customers", [{"customer": self.customer}])
		settings.save(ignore_permissions=True)
		frappe.get_cached_doc("Inter Branch Sale Settings").reload()

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
		clearing = frappe.db.sql("select sum(debit)-sum(credit) from `tabGL Entry` where account=%s and is_cancelled=0", self.accounts["clearing"])[0][0]
		self.assertAlmostEqual(flt(clearing), 0.0, places=2)

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
