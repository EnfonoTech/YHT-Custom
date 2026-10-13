# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""The client's UAT round of 2026-10-13 on the Tuesday / Wednesday batches (rows 13, 20, 22,
26, 37).

Runs on `yht-test` only (`yht_features` is `["all"]` there):

    bench --site yht-test run-tests --app yht_custom --skip-before-tests \
        --module yht_custom.tests.test_uat_feedback_1013

Nothing commits (gotcha 74); prints go through `printview.get_rendered_template(doc=…)`
(gotcha 84).
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import meeting_1011, other_remarks
from yht_custom.tests.test_meeting_1011_wednesday import (
	_a_doc,
	_fieldnames,
	_format_html,
	_inline,
	_off,
	_render,
	_source,
)

R22 = "oct11_r22_other_remarks_front"
R37 = "oct11_r37_print_heading_front"


class TestRow13OneButton(FrappeTestCase):
	"""'Right now we have two with the same function: Show Sales History and Price Assist.'"""

	def setUp(self):
		js = _source("public/js/price_assist.js")
		start = js.index("function add_grid_buttons(frm)")
		self.body = js[start : js.index("yht_custom.price.sales_history_on = function")]

	def test_with_the_switch_on_only_show_sales_history_is_added(self):
		history = self.body.index('__("Show Sales History")')
		early_return = self.body.index("return;", history)
		assist = self.body.index('__("Price Assist")')
		self.assertLess(history, early_return)
		self.assertLess(early_return, assist, "Price Assist must only be reachable when the switch is off")

	def test_with_the_switch_off_the_old_pair_is_unchanged(self):
		self.assertIn('__("Show Price History")', self.body)
		self.assertIn('__("Price Assist")', self.body)

	def test_the_script_has_a_new_cache_bust_version(self):
		self.assertIn("/assets/yht_custom/js/price_assist.js?v=10", _source("hooks.py"))


class TestRow20QuotationColumns(FrappeTestCase):
	"""'ID is showing first but the Title column is not appearing.'"""

	def _settings(self):
		raw = frappe.db.get_value("List View Settings", "Quotation", "fields")
		return [row["fieldname"] for row in json.loads(raw)]

	def test_the_id_leads_and_the_customer_name_is_a_column(self):
		meeting_1011.setup_quotation_id_first()
		meta = frappe.get_meta("Quotation")
		self.assertFalse(meta.title_field)
		self.assertEqual(frappe.get_meta("Quotation").get_field("customer_name").in_list_view, 1)
		self.assertEqual(self._settings()[0], "customer_name")

	def test_the_other_columns_are_kept_in_order(self):
		meeting_1011.setup_quotation_id_first()
		self.assertEqual(
			self._settings(), ["customer_name", "transaction_date", "status_field", "grand_total"]
		)

	def test_it_is_idempotent(self):
		meeting_1011.setup_quotation_id_first()
		before = frappe.db.get_value("List View Settings", "Quotation", ["fields", "modified"])
		meeting_1011.setup_quotation_id_first()
		self.assertEqual(frappe.db.get_value("List View Settings", "Quotation", ["fields", "modified"]), before)

	def test_it_waits_for_its_switch(self):
		with _off("oct11_r20_quotation_id_first"):
			self.assertIn("skipped", meeting_1011.setup_quotation_id_first())


class TestRow22OtherRemarks(FrappeTestCase):
	"""'Other Remarks missing from sales invoice, sales return, purchase invoice, purchase
	receipt, purchase order.'"""

	FRONT = ("Sales Invoice", "Purchase Invoice", "Purchase Receipt")

	def setUp(self):
		other_remarks.ensure_other_remarks_fields()

	def test_purchase_order_is_covered(self):
		self.assertIn("Purchase Order", other_remarks.DOCTYPES)
		self.assertIn("Purchase Order", other_remarks.ANCHORS)
		field = frappe.get_meta("Purchase Order").get_field(other_remarks.FIELDNAME)
		self.assertIsNotNone(field)
		self.assertEqual(field.allow_on_submit, 1)

	def test_purchase_order_is_in_the_fixture_filter(self):
		names = set()
		for entry in frappe.get_hooks("fixtures", app_name="yht_custom") or []:
			if isinstance(entry, dict) and entry.get("dt") == "Custom Field":
				for clause in entry.get("filters") or []:
					if len(clause) == 3 and clause[0] == "name" and clause[1] == "in":
						names.update(clause[2])
		self.assertIn("Purchase Order-custom_other_remarks", names)

	def test_the_field_is_on_the_front_page_of_the_four(self):
		meeting_1011.setup_other_remarks_front()
		for doctype in (*self.FRONT, "Purchase Order"):
			with self.subTest(doctype=doctype):
				order = _fieldnames(doctype)
				boundary = meeting_1011._front_boundary(order)
				self.assertLess(order.index(other_remarks.FIELDNAME), boundary)

	def test_it_is_a_permutation_and_idempotent(self):
		before = {dt: sorted(_fieldnames(dt)) for dt in self.FRONT}
		meeting_1011.setup_other_remarks_front()
		for dt in self.FRONT:
			self.assertEqual(sorted(_fieldnames(dt)), before[dt], f"{dt}: a field was lost or added")
		again = meeting_1011.setup_other_remarks_front()
		self.assertEqual(again["moved"], [])

	def test_it_waits_for_its_switch(self):
		with _off(R22):
			self.assertIn("skipped", meeting_1011.setup_other_remarks_front())

	def test_the_switch_and_step_are_registered(self):
		from yht_custom import features, setup

		self.assertIn(R22, features.KNOWN)
		self.assertIn("setup_other_remarks_front", setup.PROVISIONING_STEPS)
		self.assertLess(
			setup.PROVISIONING_STEPS.index("ensure_other_remarks_fields"),
			setup.PROVISIONING_STEPS.index("setup_other_remarks_front"),
			"the field must exist before it is moved",
		)


class TestRow26PromptOncePerLogin(FrappeTestCase):
	"""'The option popped up once in multiple log-in attempts.'"""

	def setUp(self):
		self.js = _source("public/js/session_year.js")

	def test_the_flag_holds_the_login_not_a_constant(self):
		self.assertIn("frappe.csrf_token", self.js)
		self.assertNotIn('sessionStorage.setItem("yht_session_year_shown", "1")', self.js)
		self.assertIn('sessionStorage.getItem("yht_session_year_shown") === login', self.js)

	def test_the_flag_is_still_set_before_the_dialog(self):
		self.assertLess(self.js.index("sessionStorage.setItem"), self.js.index("new frappe.ui.Dialog"))

	def test_the_script_has_a_new_cache_bust_version(self):
		self.assertIn("/assets/yht_custom/js/session_year.js?v=3", _source("hooks.py"))


class TestRow37PrinterIconHeading(FrappeTestCase):
	"""'Print heading is not reflecting when clicking the print icon.' On UAT the icon opens
	`YHT Quotation` / `YHT Delivery Note`, which printed a hard-coded title."""

	CASES = (
		("yht_quotation", "Quotation", "Proforma Invoice", "PROFORMA INVOICE", "QUOTATION"),
		("yht_delivery_note", "Delivery Note", "Delivery Note Return", "DELIVERY NOTE RETURN", "DELIVERY NOTE"),
	)

	def _title(self, fmt, doc):
		html = _render(doc, _inline(_format_html(fmt)))
		start = html.index('class="yht-title"')
		return html[start : html.index("</div>", start)].split(">", 1)[1].strip()

	def test_the_title_follows_the_heading(self):
		for fmt, doctype, heading, expected, _old in self.CASES:
			doc = _a_doc(doctype)
			if not doc:
				self.skipTest(f"no submitted {doctype} on this site")
			with self.subTest(fmt=fmt):
				doc.select_print_heading = heading
				self.assertEqual(self._title(fmt, doc), expected)

	def test_with_the_switch_off_the_old_title_prints(self):
		for fmt, doctype, heading, _expected, old in self.CASES:
			doc = _a_doc(doctype)
			if not doc:
				self.skipTest(f"no submitted {doctype} on this site")
			with self.subTest(fmt=fmt), _off(R37):
				doc.select_print_heading = heading
				self.assertEqual(self._title(fmt, doc), old)
