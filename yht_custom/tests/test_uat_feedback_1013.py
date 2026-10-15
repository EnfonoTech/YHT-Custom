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
from unittest import mock

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

	def setUp(self):
		# FrappeTestCase rolls back per CLASS (gotcha 50), so every test starts from "no row".
		frappe.db.delete("List View Settings", {"name": "Quotation"})

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

	def test_a_column_set_the_client_made_is_never_overwritten(self):
		meeting_1011.setup_quotation_id_first()
		custom = [
			{"fieldname": "name", "label": "ID"},
			{"fieldname": "customer_name", "label": "Customer Name"},
			{"fieldname": "contact_mobile", "label": "Mobile No"},
		]
		frappe.db.set_value("List View Settings", "Quotation", "fields", json.dumps(custom))
		meeting_1011.setup_quotation_id_first()
		self.assertEqual(json.loads(frappe.db.get_value("List View Settings", "Quotation", "fields")), custom)

	def test_a_client_set_without_the_customer_name_gets_it_after_the_first_column(self):
		meeting_1011.setup_quotation_id_first()
		custom = [{"fieldname": "name", "label": "ID"}, {"fieldname": "grand_total", "label": "Grand Total"}]
		frappe.db.set_value("List View Settings", "Quotation", "fields", json.dumps(custom))
		meeting_1011.setup_quotation_id_first()
		got = [e["fieldname"] for e in json.loads(frappe.db.get_value("List View Settings", "Quotation", "fields"))]
		self.assertEqual(got, ["name", "customer_name", "grand_total"])

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
		self.assertIn("/assets/yht_custom/js/session_year.js?v=4", _source("hooks.py"))


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


class TestClientBuiltDefaultIsNotAFail(FrappeTestCase):
	"""The client builds and re-points his own formats; `check_client_defaults` must not call that a regression."""

	def _status(self, name):
		from yht_custom import print_consolidation as pc
		from yht_custom.tests.test_client_print_defaults import _setter

		_setter("Delivery Note", name, "saheed@kathoomcompany.com")
		frappe.clear_cache(doctype="Delivery Note")
		with mock.patch("builtins.print"):
			return pc.check_client_defaults()["Delivery Note"]

	def test_an_enabled_client_built_format_of_that_doctype_is_ok(self):
		from yht_custom.tests.test_client_print_defaults import _format

		name = _format("_T-R35-CLIENT-BW", "Delivery Note")
		row = self._status(name)
		self.assertEqual(row["status"], "OK")
		self.assertIn("client-built", row["reason"])

	def test_one_of_ours_that_is_not_an_accepted_name_still_fails(self):
		from yht_custom.tests.test_client_print_defaults import _format, _one_of_ours

		_format("DELIVERY-NOTE W HEAD", "Delivery Note")  # so the SKIP branch does not answer
		row = self._status(_one_of_ours())
		self.assertEqual(row["status"], "FAIL")

	def test_a_missing_format_still_fails(self):
		from yht_custom.tests.test_client_print_defaults import _format

		_format("DELIVERY-NOTE W HEAD", "Delivery Note")
		self.assertEqual(self._status("_T-R35-NO-SUCH-FORMAT")["status"], "FAIL")


class TestDeliveryNoteHeadingOnTheClientsLayout(FrappeTestCase):
	"""The live Delivery Note has no posting date on its front page; the heading goes under the PO date."""

	LIVE_ORDER = [
		"custom_section_break_ljol1", "custom_column_break_ivq6t", "customer", "customer_name", "tax_id",
		"custom_column_break_nfypc", "po_no", "po_date", "custom_front_party_section", "customer_address",
		"address_display", "custom_front_party_col", "contact_person", "contact_display",
		"custom_front_team_section", "sales_team", "section_break1", "items",
		"posting_date", "set_posting_time", "select_print_heading",
	]

	def test_the_anchor_on_the_clients_layout_is_the_po_date(self):
		self.assertEqual(meeting_1011._front_anchor("Delivery Note", self.LIVE_ORDER), "po_date")

	def test_the_standard_layout_still_uses_the_posting_date_anchors(self):
		order = ["naming_series", "customer", "posting_date", "set_posting_time", "items"]
		self.assertEqual(meeting_1011._front_anchor("Delivery Note", order), "set_posting_time")

	def test_an_anchor_behind_the_item_table_is_never_chosen(self):
		order = ["customer", "items", "po_date"]
		self.assertIsNone(meeting_1011._front_anchor("Delivery Note", order))


class TestFieldsTheClientHadHidden(FrappeTestCase):
	"""Live had Print As and Other Remarks hidden in Customize Form (2026-10-03); the client asked to see them."""

	def _hide(self, doctype, fieldname):
		name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "name")
		frappe.db.set_value("Custom Field", name, "hidden", 1)
		frappe.clear_cache(doctype=doctype)
		return name

	def test_each_requested_field_is_unhidden(self):
		for doctype, fieldname, _switch in meeting_1011.VISIBLE_FIELDS:
			with self.subTest(doctype=doctype, field=fieldname):
				self._hide(doctype, fieldname)
				self.assertEqual(frappe.get_meta(doctype, cached=False).get_field(fieldname).hidden, 1)
				meeting_1011.setup_requested_fields_visible()
				frappe.clear_cache(doctype=doctype)
				self.assertEqual(frappe.get_meta(doctype, cached=False).get_field(fieldname).hidden, 0)

	def test_a_field_outside_the_list_stays_as_the_client_set_it(self):
		name = self._hide("Delivery Note", "custom_other_remarks")
		meeting_1011.setup_requested_fields_visible()
		self.assertEqual(frappe.db.get_value("Custom Field", name, "hidden"), 1)

	def test_it_waits_for_its_switch(self):
		self._hide("Quotation", "custom_other_remarks")
		with _off(R22):
			res = meeting_1011.setup_requested_fields_visible()
		self.assertTrue(any("Quotation.custom_other_remarks" in x for x in res["skipped"]))
		self.assertEqual(
			frappe.db.get_value("Custom Field", {"dt": "Quotation", "fieldname": "custom_other_remarks"}, "hidden"), 1
		)

	def test_quotation_has_a_front_page_anchor_for_other_remarks(self):
		self.assertIn("Quotation", meeting_1011.OTHER_REMARKS_FRONT_ANCHORS)
		meeting_1011.setup_other_remarks_front()
		order = _fieldnames("Quotation")
		self.assertLess(order.index(other_remarks.FIELDNAME), meeting_1011._front_boundary(order))

	def test_the_step_is_registered_after_the_remarks_step(self):
		from yht_custom import setup

		steps = list(setup.PROVISIONING_STEPS)
		self.assertGreater(steps.index("setup_requested_fields_visible"), steps.index("setup_other_remarks_front"))
		self.assertTrue(callable(setup._imported("setup_requested_fields_visible")))


class TestPrepaymentBlockOnlyOnReceive(FrappeTestCase):
	"""'Collapse the prepayment invoice details when Pay is opted' — the client's UAT-vs-live finding."""

	FLAG = "custom_prepayment_invoice"
	DESC = "custom_prepayment_invoice_description"

	def _cf(self, fieldname):
		return frappe.db.get_value("Custom Field", {"dt": "Payment Entry", "fieldname": fieldname}, "name")

	def _run(self):
		from yht_custom import form_layout

		frappe.clear_cache(doctype="Payment Entry")
		return form_layout.setup_prepayment_block()

	def test_blank_gates_are_filled_in_like_uat(self):
		frappe.db.set_value("Custom Field", self._cf(self.FLAG), "depends_on", "")
		frappe.db.set_value("Custom Field", self._cf(self.DESC), "depends_on", "")
		self._run()
		self.assertEqual(
			frappe.db.get_value("Custom Field", self._cf(self.FLAG), "depends_on"),
			'eval:doc.payment_type == "Receive"',
		)
		self.assertEqual(
			frappe.db.get_value("Custom Field", self._cf(self.DESC), "depends_on"),
			"eval:doc.custom_prepayment_invoice",
		)

	def test_an_expression_somebody_wrote_is_left_alone(self):
		frappe.db.set_value("Custom Field", self._cf(self.FLAG), "depends_on", "eval:doc.company")
		self._run()
		self.assertEqual(frappe.db.get_value("Custom Field", self._cf(self.FLAG), "depends_on"), "eval:doc.company")

	def test_the_three_tax_sections_carry_the_tick_and_it_is_not_stacked(self):
		from yht_custom.form_layout import PE_TAX_GATED_SECTIONS

		self._run()
		self._run()
		meta = frappe.get_meta("Payment Entry", cached=False)
		for fieldname in PE_TAX_GATED_SECTIONS:
			with self.subTest(section=fieldname):
				expr = meta.get_field(fieldname).depends_on or ""
				self.assertEqual(expr.count(self.FLAG), 1, expr)

	def test_it_waits_for_its_switch(self):
		with _off("oct08_r24_prepayment_block"):
			from yht_custom import form_layout

			self.assertIn("skipped", form_layout.setup_prepayment_block())
