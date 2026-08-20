# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Print formats and the bilingual letterhead (plan 6.4/6.5, plus the two gaps).

Read-only: every test renders a document the client already submitted.
"""

import re

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import letterhead
from yht_custom.print_helpers import yht_currency

ARABIC = re.compile(r"[؀-ۿ]")

#: (doctype, print format). Sales Invoice is absent on purpose — ksa_compliance
#: owns its printing until ZATCA onboarding.
FORMATS = (
	("Delivery Note", "YHT Delivery Note"),
	("Sales Order", "YHT Sales Order"),
	("Quotation", "YHT Quotation"),
	("Purchase Invoice", "YHT Purchase Invoice"),
	("Purchase Invoice", "YHT Expense Invoice"),
	("Journal Entry", "YHT Journal Entry"),
)


class TestPrintFormatsRender(FrappeTestCase):
	def test_every_format_is_installed_and_enabled(self):
		for doctype, print_format in FORMATS:
			with self.subTest(print_format=print_format):
				row = frappe.db.get_value(
					"Print Format", print_format, ["doc_type", "disabled", "print_format_type"], as_dict=True
				)
				self.assertTrue(row, f"{print_format} is not installed")
				self.assertEqual(row.doc_type, doctype)
				self.assertFalse(row.disabled)
				self.assertEqual(row.print_format_type, "Jinja")

	def test_every_format_renders_a_real_document(self):
		"""Journal Entry is the one that mattered: it had ZERO print formats.

		It is also the document that exposed the sandbox bug — see
		test_no_format_reaches_for_a_sandboxed_default.
		"""
		for doctype, print_format in FORMATS:
			name = frappe.db.get_value(doctype, {"docstatus": 1}, "name")
			if not name:
				continue
			with self.subTest(print_format=print_format):
				html = frappe.get_print(doctype, name, print_format=print_format)
				self.assertGreater(len(html), 2000, f"{print_format} rendered almost nothing")
				self.assertTrue(ARABIC.search(html), f"{print_format} printed no Arabic")

	def test_no_format_reaches_for_a_sandboxed_default(self):
		"""`frappe.defaults.get_global_default` is NOT callable from a print format.

		Frappe hands the template a restricted `frappe` namespace where `defaults`
		is a function, so the call raises "'function object' has no attribute
		'get_global_default'". Every format carried it and got away with it only
		because `doc.currency` short-circuited the expression. Journal Entry has no
		`currency` field, so it was the first document to reach the right-hand side
		and the whole format failed to render.
		"""
		for _doctype, print_format in FORMATS:
			with self.subTest(print_format=print_format):
				html = frappe.db.get_value("Print Format", print_format, "html") or ""
				self.assertNotIn("frappe.defaults", html)

	def test_the_currency_helper_answers_without_a_currency_field(self):
		journal = frappe.db.get_value("Journal Entry", {"docstatus": 1}, "name")
		if not journal:
			self.skipTest("no submitted Journal Entry")
		doc = frappe.get_doc("Journal Entry", journal)
		self.assertFalse(doc.get("currency"), "Journal Entry grew a currency field")
		self.assertTrue(yht_currency(doc))

	def test_the_defaults_point_at_our_formats(self):
		expected = {
			"Delivery Note": "YHT Delivery Note",
			"Quotation": "YHT Quotation",
			"Sales Order": "YHT Sales Order",
			"Purchase Invoice": "YHT Purchase Invoice",
			"Journal Entry": "YHT Journal Entry",
		}
		for doctype, print_format in expected.items():
			with self.subTest(doctype=doctype):
				self.assertEqual(
					frappe.db.get_value("DocType", doctype, "default_print_format"), print_format
				)

	def test_sales_invoice_has_no_pinned_default(self):
		"""ksa_compliance owns Sales Invoice printing until ZATCA onboarding.

		Pinning one here would override the ZATCA format on a compliance document.
		"""
		self.assertFalsy = self.assertFalse
		self.assertFalse(frappe.db.get_value("DocType", "Sales Invoice", "default_print_format"))


class TestBranchLetterhead(FrappeTestCase):
	def test_every_branch_has_a_bilingual_letterhead(self):
		for branch in frappe.get_all("Branch", pluck="name"):
			with self.subTest(branch=branch):
				name = letterhead.letter_head_name(branch)
				self.assertTrue(frappe.db.exists("Letter Head", name), f"{branch} has no letterhead")

				doc = frappe.get_doc("Letter Head", name)
				self.assertEqual(doc.source, "HTML", "an image letterhead cannot be bilingual")
				self.assertFalse(doc.disabled)
				self.assertTrue(ARABIC.search(doc.content or ""), "no Arabic in the letterhead")

	def test_the_branch_links_to_its_letterhead(self):
		for branch in frappe.get_all("Branch", fields=["name", "custom_letter_head"]):
			with self.subTest(branch=branch.name):
				self.assertEqual(branch.custom_letter_head, letterhead.letter_head_name(branch.name))

	def test_the_letterhead_carries_the_vat_number(self):
		company = frappe.db.get_value("Company", {}, ["name", "tax_id"], as_dict=True)
		if not (company and company.tax_id):
			self.skipTest("company has no VAT number")
		branch = frappe.db.get_value("Branch", {}, "name")
		content = frappe.db.get_value("Letter Head", letterhead.letter_head_name(branch), "content")
		self.assertIn(company.tax_id, content)

	def test_the_company_default_is_left_alone(self):
		"""1,515 invoices print with the client's image letterhead.

		Switching the company default would silently change all of them. That is
		the client's decision to make, not this app's.
		"""
		default = frappe.db.get_value("Company", {}, "default_letter_head")
		if not default:
			self.skipTest("no company default letterhead")
		self.assertFalse(
			default.startswith(letterhead.PREFIX),
			"a generated letterhead was made the company default",
		)

	def test_provisioning_is_idempotent(self):
		first = letterhead.setup_branch_letterheads()
		second = letterhead.setup_branch_letterheads()
		self.assertEqual(second["created"], 0)
		self.assertEqual(second["updated"], 0)
		self.assertEqual(second["unchanged"], first["created"] + first["updated"] + first["unchanged"])
