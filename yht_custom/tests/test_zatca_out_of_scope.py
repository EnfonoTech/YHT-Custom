# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""2026-10-16 — an invoice that only covers 'Not subject to VAT' supplies is not reported to ZATCA.

    bench --site yht-test run-tests --app yht_custom --skip-before-tests \
        --module yht_custom.tests.test_zatca_out_of_scope
"""

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import features, zatca_out_of_scope as oos
from yht_custom.tests.test_meeting_1011_wednesday import _off


def _doc(rows, template=None, name="TEST-OOS-0001", tax=0):
	doc = frappe._dict(doctype="Sales Invoice", name=name, taxes_and_charges=template, total_taxes_and_charges=tax)
	doc["items"] = [frappe._dict(item_tax_template=t) for t in rows]
	doc.add_comment = mock.Mock()
	return doc


class _Cats:
	"""Stands in for `map_tax_category` and the Tax Category lookup: item template -> code."""

	def __init__(self, item_templates=None, tax_categories=None, template_tax_category=None):
		self.item_templates = item_templates or {}
		self.tax_categories = tax_categories or {}
		self.template_tax_category = template_tax_category or {}

	def map(self, tax_category_id=None, item_tax_template_id=None):
		code = self.tax_categories[tax_category_id] if tax_category_id else self.item_templates[item_tax_template_id]
		return mock.Mock(tax_category_code=code)

	def get_value(self, doctype, name, fieldname, *a, **k):
		assert doctype == "Sales Taxes and Charges Template" and fieldname == "tax_category"
		return self.template_tax_category.get(name)

	def patches(self):
		return (
			mock.patch("ksa_compliance.standard_doctypes.tax_category.map_tax_category", side_effect=self.map),
			mock.patch.object(frappe.db, "get_value", side_effect=self.get_value),
		)


class TestCategoryDecision(FrappeTestCase):
	def _decide(self, doc, cats):
		a, b = cats.patches()
		with a, b:
			return oos.is_out_of_scope_only(doc)

	def test_header_zero_rated_with_no_item_templates_is_out_of_scope(self):
		cats = _Cats(tax_categories={"Zero Rated": "O"}, template_tax_category={"Zero Rated - KATC": "Zero Rated"})
		self.assertTrue(self._decide(_doc([None, None], template="Zero Rated - KATC"), cats))

	def test_header_standard_rate_is_reported(self):
		cats = _Cats(tax_categories={"Sales": "S"}, template_tax_category={"SALES VAT 15% - KATC": "Sales"})
		self.assertFalse(self._decide(_doc([None], template="SALES VAT 15% - KATC"), cats))

	def test_every_line_out_of_scope_by_its_item_template(self):
		cats = _Cats(item_templates={"Zero Rated - KATC": "O"})
		self.assertTrue(self._decide(_doc(["Zero Rated - KATC", "Zero Rated - KATC"]), cats))

	def test_one_standard_rate_line_makes_the_invoice_reported(self):
		cats = _Cats(item_templates={"Zero Rated - KATC": "O", "SALES VAT 15% - KATC": "S"})
		self.assertFalse(self._decide(_doc(["Zero Rated - KATC", "SALES VAT 15% - KATC"]), cats))

	def test_the_ksin_26_0747_shape_is_out_of_scope_by_what_is_charged(self):
		"""Header says Zero Rated, no tax is charged, but the line carries the 15% item template (the app
		would class it S and report an invoice that contradicts itself): the header and the nil tax decide."""
		cats = _Cats(
			item_templates={"SALES VAT 15% - KATC": "S"},
			tax_categories={"Zero Rated": "O"},
			template_tax_category={"Zero Rated - KATC": "Zero Rated"},
		)
		self.assertTrue(self._decide(_doc(["SALES VAT 15% - KATC"], template="Zero Rated - KATC", tax=0), cats))

	def test_a_zero_rated_header_with_tax_actually_charged_is_reported(self):
		cats = _Cats(
			item_templates={"SALES VAT 15% - KATC": "S"},
			tax_categories={"Zero Rated": "O"},
			template_tax_category={"Zero Rated - KATC": "Zero Rated"},
		)
		self.assertFalse(self._decide(_doc(["SALES VAT 15% - KATC"], template="Zero Rated - KATC", tax=0.15), cats))

	def test_a_standard_header_with_no_tax_is_still_reported(self):
		cats = _Cats(
			item_templates={"SALES VAT 15% - KATC": "S"},
			tax_categories={"Sales": "S"},
			template_tax_category={"SALES VAT 15% - KATC": "Sales"},
		)
		self.assertFalse(self._decide(_doc(["SALES VAT 15% - KATC"], template="SALES VAT 15% - KATC", tax=0), cats))

	def test_a_line_without_template_uses_the_header_category(self):
		cats = _Cats(
			item_templates={"Zero Rated - KATC": "O"},
			tax_categories={"Zero Rated": "O"},
			template_tax_category={"Zero Rated - KATC": "Zero Rated"},
		)
		self.assertTrue(self._decide(_doc(["Zero Rated - KATC", None], template="Zero Rated - KATC"), cats))

	def test_nothing_to_decide_from_means_reported(self):
		cats = _Cats()
		self.assertFalse(self._decide(_doc([]), cats))  # no lines
		self.assertFalse(self._decide(_doc([None]), cats))  # no template, no item template
		cats = _Cats(template_tax_category={"T": None})
		self.assertFalse(self._decide(_doc([None], template="T"), cats))  # template without a Tax Category


class TestTheHook(FrappeTestCase):
	def setUp(self):
		from ksa_compliance.standard_doctypes import sales_invoice

		self.si = sales_invoice
		sales_invoice.clear_additional_fields_ignore_list()
		self.addCleanup(sales_invoice.clear_additional_fields_ignore_list)

	def _run(self, doc, out_of_scope):
		with mock.patch.object(oos, "is_out_of_scope_only", return_value=out_of_scope):
			oos.skip_zatca_for_out_of_scope(doc)

	def test_an_out_of_scope_invoice_is_put_on_the_ignore_list_and_noted(self):
		doc = _doc([None])
		self._run(doc, True)
		self.assertIn(doc.name, self.si.IGNORED_INVOICES)
		doc.add_comment.assert_called_once()
		self.assertIn("Not reported to ZATCA", doc.add_comment.call_args.args[1])

	def test_a_reported_invoice_is_left_alone(self):
		doc = _doc([None])
		self._run(doc, False)
		self.assertNotIn(doc.name, self.si.IGNORED_INVOICES)
		doc.add_comment.assert_not_called()

	def test_it_waits_for_its_switch(self):
		doc = _doc([None])
		with _off(oos.FEATURE):
			self._run(doc, True)
		self.assertNotIn(doc.name, self.si.IGNORED_INVOICES)

	def test_other_doctypes_are_ignored(self):
		doc = _doc([None])
		doc.doctype = "POS Invoice"
		self._run(doc, True)
		self.assertNotIn(doc.name, self.si.IGNORED_INVOICES)

	def test_a_failure_never_blocks_the_submit_and_the_invoice_is_reported(self):
		doc = _doc([None])
		with mock.patch.object(oos, "is_out_of_scope_only", side_effect=RuntimeError("boom")), mock.patch.object(
			frappe, "log_error"
		) as log:
			oos.skip_zatca_for_out_of_scope(doc)  # must not raise
		self.assertNotIn(doc.name, self.si.IGNORED_INVOICES)
		log.assert_called_once()

	def test_the_switch_is_known_and_the_hook_is_registered_before_submit(self):
		self.assertIn(oos.FEATURE, features.KNOWN)
		hooks = frappe.get_hooks("doc_events", app_name="yht_custom") or {}
		handlers = (hooks.get("Sales Invoice") or {}).get("before_submit") or []
		handlers = handlers if isinstance(handlers, list) else [handlers]
		self.assertIn("yht_custom.zatca_out_of_scope.skip_zatca_for_out_of_scope", handlers)


class TestKsaComplianceHonoursTheIgnoreList(FrappeTestCase):
	"""The real `ksa_compliance` on_submit handler: an ignored invoice gets no Additional Fields record."""

	def _submit(self, name):
		from ksa_compliance.standard_doctypes import sales_invoice as si

		doc = frappe._dict(doctype="Sales Invoice", name=name, company="X", is_consolidated=0)
		settings = mock.Mock(enable_zatca_integration=1, is_live_sync=0)
		with mock.patch.object(si, "_should_enable_zatca_for_invoice", return_value=True), mock.patch.object(
			si.ZATCABusinessSettings, "for_invoice", return_value=settings
		), mock.patch.object(si.SalesInvoiceAdditionalFields, "create_for_invoice") as create, mock.patch.object(
			si.ZATCAPrecomputedInvoice, "for_invoice", return_value=None
		):
			si.create_sales_invoice_additional_fields_doctype(doc, "on_submit")
		return create

	def test_ignored_invoice_creates_nothing_and_a_normal_one_does(self):
		from ksa_compliance.standard_doctypes import sales_invoice as si

		si.clear_additional_fields_ignore_list()
		self.addCleanup(si.clear_additional_fields_ignore_list)
		si.ignore_additional_fields_for_invoice("TEST-IGNORED")
		self.assertFalse(self._submit("TEST-IGNORED").called)
		self.assertTrue(self._submit("TEST-NORMAL").called)
