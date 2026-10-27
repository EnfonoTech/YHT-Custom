# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Client sheet, rows escalated 2026-10-26 — four fields taken off the forms.

Runs on `yht-test` only (`yht_features` is `["all"]` there):

    bench --site yht-test run-tests --app yht_custom --skip-before-tests \
        --module yht_custom.tests.test_meeting_1027

Nothing commits (gotcha 74). Each class restores the `hidden` flags it flips in a `finally`, because
`FrappeTestCase` rolls back once per CLASS, not per test (gotcha 50).
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import attention_field, features, meeting_1011, meeting_1027, other_remarks
from yht_custom.tests.test_meeting_1011_wednesday import _off

SWITCHES = (
	meeting_1027.OTHER_REMARKS,
	meeting_1027.CASH_DUE_DATE,
	meeting_1027.COMPANY_TAX_ID,
	meeting_1027.ATTENTION,
)


def _hidden(doctype, fieldname):
	frappe.clear_cache(doctype=doctype)
	df = frappe.get_meta(doctype, cached=False).get_field(fieldname)
	return df.hidden if df else None


def _unhide(doctype, fieldname):
	frappe.db.set_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "hidden", 0)
	frappe.clear_cache(doctype=doctype)


class TestSwitches(FrappeTestCase):
	def test_every_switch_is_known(self):
		for name in SWITCHES:
			with self.subTest(switch=name):
				self.assertIn(name, features.KNOWN)
				features.enabled(name)  # must not raise

	def test_the_steps_are_provisioned_after_the_fields_they_hide(self):
		from yht_custom.setup import PROVISIONING_STEPS as steps

		self.assertLess(steps.index("setup_requested_fields_visible"), steps.index("setup_other_remarks_hidden"))
		self.assertLess(steps.index("ensure_attention_field"), steps.index("setup_attention_hidden"))


class TestOtherRemarksHidden(FrappeTestCase):
	def test_hidden_on_every_doctype_that_has_it(self):
		present = [dt for dt in other_remarks.DOCTYPES if frappe.get_meta(dt).has_field(other_remarks.FIELDNAME)]
		self.assertTrue(present, "no doctype carries Other Remarks on this site")
		try:
			for dt in present:
				_unhide(dt, other_remarks.FIELDNAME)
			meeting_1027.setup_other_remarks_hidden()
			for dt in present:
				with self.subTest(doctype=dt):
					self.assertEqual(_hidden(dt, other_remarks.FIELDNAME), 1)
		finally:
			frappe.db.rollback()

	def test_the_column_and_its_text_stay(self):
		meeting_1027.setup_other_remarks_hidden()
		for dt in other_remarks.DOCTYPES:
			if frappe.get_meta(dt).has_field(other_remarks.FIELDNAME):
				with self.subTest(doctype=dt):
					self.assertTrue(frappe.db.has_column(dt, other_remarks.FIELDNAME))
					self.assertTrue(frappe.db.exists("Custom Field", {"dt": dt, "fieldname": other_remarks.FIELDNAME}))

	def test_the_row22_unhide_step_does_not_bring_it_back(self):
		meeting_1027.setup_other_remarks_hidden()
		result = meeting_1011.setup_requested_fields_visible()
		self.assertFalse([s for s in result["shown"] if s.endswith(other_remarks.FIELDNAME)])
		self.assertEqual(_hidden("Sales Invoice", other_remarks.FIELDNAME), 1)

	def test_the_row22_unhide_step_still_works_with_the_switch_off(self):
		"""The live site keeps its current behaviour until it asks for the new switch."""
		try:
			_unhide("Quotation", other_remarks.FIELDNAME)
			with _off(meeting_1027.OTHER_REMARKS):
				self.assertIn("skipped", meeting_1027.setup_other_remarks_hidden())
				meeting_1011.setup_requested_fields_visible()
			self.assertEqual(_hidden("Quotation", other_remarks.FIELDNAME), 0)
		finally:
			frappe.db.rollback()

	def test_idempotent(self):
		meeting_1027.setup_other_remarks_hidden()
		self.assertEqual(meeting_1027.setup_other_remarks_hidden(), {"hidden": []})


class TestCashHidesDueDate(FrappeTestCase):
	def test_due_date_depends_on_the_payment_mode(self):
		meeting_1027.setup_cash_hides_due_date()
		frappe.clear_cache(doctype="Sales Invoice")
		df = frappe.get_meta("Sales Invoice", cached=False).get_field("due_date")
		self.assertEqual(df.depends_on, meeting_1027.DUE_DATE_DEPENDS_ON)

	def test_the_condition_names_a_real_field_and_option(self):
		"""A typo in either would hide nothing, silently."""
		df = frappe.get_meta("Sales Invoice").get_field("custom_payment_mode")
		self.assertIsNotNone(df)
		self.assertIn("Cash", (df.options or "").split("\n"))
		self.assertIn("custom_payment_mode", meeting_1027.DUE_DATE_DEPENDS_ON)

	def test_the_stored_date_is_not_touched(self):
		"""Only the form changes: the field stays non-mandatory and keeps no default of ours."""
		meeting_1027.setup_cash_hides_due_date()
		self.assertFalse(
			frappe.db.exists(
				"Property Setter", {"doc_type": "Sales Invoice", "field_name": "due_date", "property": ["in", ["reqd", "default", "hidden"]]}
			)
		)

	def test_it_waits_for_its_switch(self):
		with _off(meeting_1027.CASH_DUE_DATE):
			self.assertIn("skipped", meeting_1027.setup_cash_hides_due_date())


class TestCompanyTaxIdHidden(FrappeTestCase):
	def test_hidden_on_the_sales_invoice(self):
		meeting_1027.setup_company_tax_id_hidden()
		self.assertEqual(_hidden("Sales Invoice", "company_tax_id"), 1)

	def test_the_customer_tax_id_is_left_alone(self):
		"""`tax_id` is the BUYER's VAT number and the client wants it visible (KSIN-26-0751)."""
		def tax_id_setters():
			return frappe.get_all(
				"Property Setter", filters={"field_name": "tax_id"}, fields=["name", "value", "modified"], order_by="name"
			)

		before = tax_id_setters()
		meeting_1027.setup_company_tax_id_hidden()
		self.assertEqual(tax_id_setters(), before)

	def test_it_waits_for_its_switch(self):
		with _off(meeting_1027.COMPANY_TAX_ID):
			self.assertIn("skipped", meeting_1027.setup_company_tax_id_hidden())


class TestAttentionHidden(FrappeTestCase):
	def test_hidden_on_the_four_selling_doctypes(self):
		try:
			for dt in attention_field.DOCTYPES:
				_unhide(dt, attention_field.FIELDNAME)
			result = meeting_1027.setup_attention_hidden()
			self.assertEqual(sorted(result["hidden"]), sorted(attention_field.DOCTYPES))
			for dt in attention_field.DOCTYPES:
				with self.subTest(doctype=dt):
					self.assertEqual(_hidden(dt, attention_field.FIELDNAME), 1)
		finally:
			frappe.db.rollback()

	def test_it_waits_for_its_switch(self):
		with _off(meeting_1027.ATTENTION):
			self.assertIn("skipped", meeting_1027.setup_attention_hidden())
