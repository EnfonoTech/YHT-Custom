# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""The five small change requests from the client meeting of 2026-09-23.

CR-009 salesperson · CR-010 bank details · CR-011 Attention · CR-016 Customer
sort · CR-017 Item sort (verification only).

Each assertion here is aimed at the actual complaint, not at the configuration
that is supposed to produce it — the CR-009 bug was live for months precisely
because the helper existed, was wired into the template, and still printed the
wrong name.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom.attention_field import DOCTYPES as ATTENTION_DOCTYPES
from yht_custom.attention_field import FIELDNAME as ATTENTION_FIELD
from yht_custom.link_sort import DELIBERATELY_UNSORTED, LINK_SORT
from yht_custom.print_helpers import yht_bank_details, yht_sales_person


class TestSalesPersonComesFromTheCustomer(FrappeTestCase):
	"""CR-009. The complaint was 'it prints Created By'."""

	def test_it_returns_a_dict_with_both_keys(self):
		doc = frappe.new_doc("Quotation")
		out = yht_sales_person(doc)
		self.assertIsInstance(out, dict)
		self.assertEqual(set(out), {"name", "mobile"})

	def test_quotation_has_no_sales_team_table_at_all(self):
		"""The actual mechanism behind the bug, asserted so it is not re-guessed.

		ERPNext ships no `sales_team` on Quotation — not hidden, absent. Step 1 of
		the helper therefore cannot fire there, which is why the print always
		showed the creator. Sales Order / Sales Invoice / Delivery Note do have it.
		"""
		self.assertIsNone(frappe.get_meta("Quotation").get_field("sales_team"))
		for dt in ("Sales Order", "Sales Invoice", "Delivery Note"):
			with self.subTest(doctype=dt):
				self.assertIsNotNone(frappe.get_meta(dt).get_field("sales_team"))

	def test_the_documents_own_sales_team_wins_where_the_table_exists(self):
		doc = frappe.new_doc("Sales Order")
		doc.append("sales_team", {"sales_person": "_A Person", "allocated_percentage": 100})
		self.assertEqual(yht_sales_person(doc)["name"], "_A Person")

	def test_it_falls_back_to_the_customer_when_the_document_has_none(self):
		"""The whole point of CR-009: 0 of 2,999 quotations carry a Sales Team row."""
		row = frappe.db.sql(
			"""select st.parent, st.sales_person from `tabSales Team` st
			   where st.parenttype = 'Customer' and ifnull(st.sales_person, '') != ''
			   limit 1""",
			as_dict=True,
		)
		if not row:
			self.skipTest("no customer on this site carries a salesperson")
		doc = frappe.new_doc("Quotation")
		doc.quotation_to = "Customer"
		doc.party_name = row[0].parent
		self.assertEqual(yht_sales_person(doc)["name"], row[0].sales_person)

	def test_name_and_mobile_always_describe_the_same_person(self):
		"""Never borrow the creator's number to sit beside a salesperson's name.

		Measured on the client site: only 1 of 26 Sales Persons has a reachable
		number, so "" is the normal result and must not be back-filled.
		"""
		row = frappe.db.sql(
			"""select st.parent, st.sales_person from `tabSales Team` st
			   join `tabSales Person` sp on sp.name = st.sales_person
			   where st.parenttype = 'Customer' and ifnull(sp.employee, '') = ''
			   limit 1""",
			as_dict=True,
		)
		if not row:
			self.skipTest("every salesperson here has an employee link")
		doc = frappe.new_doc("Quotation")
		doc.quotation_to = "Customer"
		doc.party_name = row[0].parent
		doc.owner = "Administrator"
		out = yht_sales_person(doc)
		self.assertEqual(out["name"], row[0].sales_person)
		self.assertEqual(out["mobile"], "", "a salesperson with no number must not inherit one")


class TestBankDetailsStillResolve(FrappeTestCase):
	"""CR-010. Reported as missing; measured as already working."""

	def test_the_helper_returns_the_designated_account(self):
		out = yht_bank_details()
		self.assertEqual(set(out), {"bank", "iban", "account_no"})

	def test_it_is_all_or_nothing(self):
		"""Never a half-populated block — an IBAN line with no number is worse."""
		out = yht_bank_details()
		if out["iban"] or out["account_no"]:
			self.assertTrue(out["bank"], "a bank block without a bank name is half-populated")


class TestAttentionField(FrappeTestCase):
	"""CR-011."""

	def test_it_exists_on_every_selling_doctype(self):
		missing = [
			dt for dt in ATTENTION_DOCTYPES if not frappe.get_meta(dt).get_field(ATTENTION_FIELD)
		]
		self.assertFalse(missing, f"Attention field missing on: {missing}")

	def test_it_is_plain_text_and_editable_after_submit(self):
		for dt in ATTENTION_DOCTYPES:
			df = frappe.get_meta(dt).get_field(ATTENTION_FIELD)
			if not df:
				continue
			with self.subTest(doctype=dt):
				self.assertEqual(df.fieldtype, "Data", "a Link would force a Contact record")
				self.assertTrue(df.allow_on_submit)

	def test_the_print_renders_it_only_when_filled(self):
		import os

		path = os.path.join(
			frappe.get_app_path("yht_custom"), "templates", "includes", "katc", "quotation.html"
		)
		body = open(path, encoding="utf-8").read()
		self.assertIn(ATTENTION_FIELD, body)
		# 🔴 The legacy orphan column must never be read again — it holds terms text.
		self.assertNotIn('doc.get("custom_attention")', body)
		self.assertIn(f'{{%- if doc.get("{ATTENTION_FIELD}") %}}', body)


class TestLinkSortOrder(FrappeTestCase):
	"""CR-016 and CR-017."""

	def test_customer_picker_sorts_by_name_ascending(self):
		meta = frappe.get_meta("Customer")
		self.assertEqual(meta.sort_field, "customer_name")
		self.assertEqual((meta.sort_order or "").upper(), "ASC")

	def test_item_is_left_alone(self):
		"""CR-017 asked us to CONFIRM, not to change. Guards against a helpful fix."""
		for doctype in DELIBERATELY_UNSORTED:
			self.assertNotIn(doctype, LINK_SORT, f"{doctype} was never in scope")
			self.assertFalse(
				frappe.db.exists(
					"Property Setter",
					{"doc_type": doctype, "property": "sort_field", "doctype_or_field": "DocType"},
				),
				f"{doctype}'s sort order is the client's existing behaviour — do not set it",
			)

	def test_the_sort_field_actually_exists(self):
		"""A sort against a missing column breaks every list AND every picker."""
		for doctype, (field, _order) in LINK_SORT.items():
			with self.subTest(doctype=doctype):
				self.assertTrue(frappe.get_meta(doctype).get_field(field))
