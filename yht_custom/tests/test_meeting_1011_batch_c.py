# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Meeting of 2026-10-11 — the Tuesday batch (sheet rows 17, 20, 24, 27, 28, 29, 34, 36, 37).

Runs on `yht-test`, where `yht_features` is `["all"]`. Anything that needs a switch OFF
patches `features.enabled`. Nothing here commits and nothing renders through
`frappe.get_print` (gotcha 84).
"""

import json
import pathlib
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import (
	branch_print_format,
	branch_purchase_order,
	features,
	meeting_1011,
	print_heading,
	zatca_buyer,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRANCH_USER = "branchtest@yht-khobhar.enfonoerp.com"

SWITCHES = (
	"oct11_r17_print_with_arabic",
	"oct11_r20_quotation_id_first",
	"oct11_r27_type_filter",
	"oct11_r28_zatca_additional_number",
	"oct11_r29_branch_purchase_order",
	"oct11_r36_branch_print_format",
	"oct11_r37_print_heading_front",
)


def _source(relative: str) -> str:
	return (ROOT / relative).read_text()


def _off(*names):
	"""`features.enabled` with the named switches forced off, the rest as configured."""
	real = features.enabled
	return mock.patch.object(
		features, "enabled", side_effect=lambda n: False if n in names else real(n)
	)


class TestTheSwitchesAreRegistered(FrappeTestCase):
	def test_every_switch_is_known(self):
		for name in SWITCHES:
			with self.subTest(switch=name):
				self.assertIn(name, features.KNOWN)
				features.enabled(name)  # must not raise

	def test_the_scripts_spell_their_switch_exactly(self):
		pairs = (
			("public/js/list_type_filter.js", "oct11_r27_type_filter"),
			("public/js/katc_print_buttons.js", "oct11_r17_print_with_arabic"),
			("public/js/branch_user_restrict.js", "oct11_r29_branch_purchase_order"),
			("yht_custom/page/yht_dashboard/yht_dashboard.js", "oct11_r29_branch_purchase_order"),
			("yht_custom/doctype/branch_configuration/branch_configuration.js", "oct11_r36_branch_print_format"),
		)
		for path, name in pairs:
			with self.subTest(file=path):
				self.assertIn(f'"{name}"', _source(path))

	def test_the_python_modules_spell_their_switch_exactly(self):
		self.assertEqual(zatca_buyer.FEATURE, "oct11_r28_zatca_additional_number")
		self.assertEqual(branch_purchase_order.FEATURE, "oct11_r29_branch_purchase_order")
		self.assertEqual(branch_print_format.FEATURE, "oct11_r36_branch_print_format")


# ------------------------------------------------------------------- row 20


class TestQuotationListOpensOnTheId(FrappeTestCase):
	def test_title_field_is_cleared_not_set_to_name(self):
		"""`title_field = "name"` empties every list (list_columns docstring); an empty
		one is what the client already runs on four other doctypes."""
		meeting_1011.setup_quotation_id_first()
		self.assertFalse(frappe.get_meta("Quotation").title_field)
		self.assertNotEqual(frappe.get_meta("Quotation").title_field, "name")

	def test_it_waits_for_its_switch(self):
		with _off("oct11_r20_quotation_id_first"):
			self.assertIn("skipped", meeting_1011.setup_quotation_id_first())


# ------------------------------------------------------------- rows 17 and 34


class TestPrintWithArabicTick(FrappeTestCase):
	def setUp(self):
		meeting_1011.setup_print_with_arabic()

	def test_the_tick_exists_on_all_four_and_can_be_changed_after_submit(self):
		for doctype in meeting_1011.SELLING:
			with self.subTest(doctype=doctype):
				field = frappe.get_meta(doctype).get_field("custom_print_with_arabic")
				self.assertIsNotNone(field)
				self.assertEqual(field.fieldtype, "Check")
				self.assertEqual(int(field.allow_on_submit or 0), 1)

	def test_the_step_is_idempotent_and_never_duplicates(self):
		meeting_1011.setup_print_with_arabic()
		for doctype in meeting_1011.SELLING:
			count = frappe.db.count("Custom Field", {"dt": doctype, "fieldname": "custom_print_with_arabic"})
			self.assertEqual(count, 1, doctype)

	def test_a_field_the_client_already_built_is_adopted_not_replaced(self):
		name = frappe.db.get_value("Custom Field", {"dt": "Quotation", "fieldname": "custom_print_with_arabic"}, "name")
		frappe.db.set_value("Custom Field", name, {"label": "Print With Arabic (client)", "allow_on_submit": 0})
		result = meeting_1011.setup_print_with_arabic()
		self.assertIn("Quotation", result["adopted"])
		self.assertEqual(
			frappe.db.get_value("Custom Field", name, "label"), "Print With Arabic (client)"
		)

	def test_the_tick_alone_asks_for_arabic(self):
		with _off("cr_004_print_heading"):
			self.assertEqual(print_heading.yht_print_lang(frappe._dict(custom_print_with_arabic=1)), "ar")
			self.assertEqual(print_heading.yht_print_lang(frappe._dict(custom_print_with_arabic=0)), "en")
			self.assertEqual(print_heading.yht_print_lang(), "en")

	def test_with_the_switch_off_the_tick_changes_nothing(self):
		with _off("oct11_r17_print_with_arabic", "cr_004_print_heading"):
			self.assertEqual(print_heading.yht_print_lang(frappe._dict(custom_print_with_arabic=1)), "en")

	def _quotation(self):
		name = frappe.db.get_value("Quotation", {"docstatus": 1}, "name", order_by="modified desc")
		if not name:
			self.skipTest("no submitted Quotation on this site")
		return frappe.get_doc("Quotation", name)

	def _render(self, doc):
		from frappe.www.printview import get_rendered_template

		html = json.loads(_source("yht_custom/print_format/katc_quotation/katc_quotation.json"))["html"]
		print_format = frappe.get_doc(
			{
				"doctype": "Print Format",
				"name": "_T-R17-shim",
				"doc_type": "Quotation",
				"module": "Yht Custom",
				"print_format_type": "Jinja",
				"custom_format": 1,
				"standard": "No",
				"html": html,
			}
		)
		return get_rendered_template(doc, print_format=print_format, no_letterhead=1)

	def test_a_ticked_quotation_prints_the_arabic_column_on_the_plain_format(self):
		doc = self._quotation()
		# The newest quotation may carry Print As = Proforma, which routes to the
		# proforma layout; this test is about the plain quotation layout.
		doc.custom_print_as = "Sales Quotation"
		doc.select_print_heading = "Sales Quotation"
		doc.custom_print_with_arabic = 0
		plain = self._render(doc)
		doc.custom_print_with_arabic = 1
		arabic = self._render(doc)
		self.assertNotIn("katc-ar-col", plain)
		self.assertIn("katc-ar-col", arabic)

	def test_the_templates_pass_the_document(self):
		for name in ("quotation", "proforma_invoice", "sales_order"):
			with self.subTest(template=name):
				source = _source(f"templates/includes/katc/{name}.html")
				self.assertIn('yht_print_lang(doc) == "ar"', source)

	def test_the_toolbar_keeps_one_print_button_but_delivery_note_keeps_two(self):
		source = _source("public/js/katc_print_buttons.js")
		self.assertIn("katc_single_button()", source)
		self.assertIn('doctype !== "Delivery Note"', source)
		self.assertIn("specs.slice(0, 1)", source)


# ------------------------------------------------------------------- row 37


class TestPrintHeadingOnTheFrontPage(FrappeTestCase):
	def setUp(self):
		meeting_1011.setup_heading_front()

	def _index(self, doctype, fieldname):
		return [f.fieldname for f in frappe.get_meta(doctype).fields].index(fieldname)

	def test_the_heading_sits_before_the_item_table_on_all_four(self):
		for doctype in meeting_1011.SELLING:
			with self.subTest(doctype=doctype):
				order = [f.fieldname for f in frappe.get_meta(doctype).fields]
				boundary = meeting_1011._front_boundary(order)
				self.assertLess(self._index(doctype, "select_print_heading"), boundary)

	def test_the_tick_sits_directly_under_the_heading(self):
		meeting_1011.setup_print_with_arabic()
		for doctype in meeting_1011.SELLING:
			with self.subTest(doctype=doctype):
				self.assertEqual(
					self._index(doctype, "custom_print_with_arabic"),
					self._index(doctype, "select_print_heading") + 1,
				)

	def test_a_second_run_changes_nothing(self):
		before = {d: [f.fieldname for f in frappe.get_meta(d).fields] for d in meeting_1011.SELLING}
		meeting_1011.setup_heading_front()
		meeting_1011.setup_print_with_arabic()
		for doctype in meeting_1011.SELLING:
			self.assertEqual(before[doctype], [f.fieldname for f in frappe.get_meta(doctype).fields])

	def test_no_field_is_dropped_or_added(self):
		for doctype in meeting_1011.SELLING:
			order = [f.fieldname for f in frappe.get_meta(doctype).fields]
			self.assertEqual(len(order), len(set(order)), doctype)

	def test_the_boot_map_offers_only_headings_that_exist(self):
		mapping = print_heading.boot_map()
		self.assertEqual(set(mapping), set(meeting_1011.SELLING))
		for doctype, entry in mapping.items():
			for key in ("fwd", "ret"):
				if entry[key]:
					self.assertTrue(frappe.db.exists("Print Heading", entry[key]), (doctype, entry))
		self.assertEqual(mapping["Delivery Note"]["ret"], "Delivery Note Return")

	def test_the_boot_map_waits_for_its_switch(self):
		with _off("oct11_r37_print_heading_front"):
			self.assertEqual(print_heading.boot_map(), {})

	def test_the_script_only_replaces_what_it_could_have_put_there(self):
		source = _source("public/js/print_heading_front.js")
		self.assertIn("defaults_of(frm.doctype).indexOf(current) === -1", source)
		self.assertIn("frm.doc.docstatus !== 0", source)
		self.assertIn("frm.is_new()", source)

	def test_the_script_is_registered_on_all_four(self):
		registered = frappe.get_hooks("doctype_js", app_name="yht_custom") or {}
		for doctype in meeting_1011.SELLING:
			entry = registered.get(doctype)
			entries = entry if isinstance(entry, list) else [entry]
			self.assertTrue(any("print_heading_front.js" in str(e) for e in entries), doctype)


# ------------------------------------------------------------------- row 24


class TestPaymentEntryOpensOnPay(FrappeTestCase):
	def test_the_default_is_pay_and_the_block_waits_for_receive(self):
		from yht_custom import form_layout

		form_layout.setup_prepayment_block()
		frappe.clear_cache(doctype="Payment Entry")
		meta = frappe.get_meta("Payment Entry")
		self.assertEqual(meta.get_field("payment_type").default, "Pay")
		self.assertIn("Receive", meta.get_field("custom_prepayment_invoice").depends_on or "")


# ------------------------------------------------------------------- row 27


class TestTypeFilterScript(FrappeTestCase):
	def test_it_is_registered_beside_list_defaults_on_four_lists(self):
		registered = frappe.get_hooks("doctype_list_js", app_name="yht_custom") or {}
		for doctype in ("Sales Invoice", "Delivery Note", "Purchase Invoice", "Purchase Receipt"):
			with self.subTest(doctype=doctype):
				entry = registered.get(doctype)
				entries = entry if isinstance(entry, list) else [entry]
				joined = " ".join(str(e) for e in entries)
				self.assertIn("list_type_filter.js", joined)
				self.assertIn("list_defaults.js", joined)

	def test_every_choice_maps_to_real_columns(self):
		"""The dropdown is virtual, so each filter it emits must name a column the
		list can actually query."""
		columns = {
			"Sales Invoice": ("is_return",),
			"Delivery Note": ("is_return",),
			"Purchase Invoice": ("is_return", "custom_is_expense_invoice"),
			"Purchase Receipt": ("is_return",),
		}
		for doctype, names in columns.items():
			meta = frappe.get_meta(doctype)
			for name in names:
				self.assertIsNotNone(meta.get_field(name), f"{doctype}.{name}")

	def test_the_script_merges_and_never_assigns(self):
		import re

		source = _source("public/js/list_type_filter.js")
		self.assertIsNone(re.search(r"frappe\.listview_settings\[[^\]]+\]\s*=\s*\{", source))
		self.assertIn("settings.onload", source)
		self.assertIn("previous.call(this, listview)", source)

	def test_the_native_checks_are_hidden_not_deleted(self):
		source = _source("public/js/list_type_filter.js")
		self.assertIn(".hide()", source)
		self.assertNotIn("delete listview.page.fields_dict", source)


# ------------------------------------------------------------------- row 28


class TestZatcaBuyerAdditionalNumber(FrappeTestCase):
	def _address(self, number):
		return frappe._dict(
			address_line1="Street 1",
			address_line2="",
			city="Khobar",
			pincode="31952",
			state="Eastern",
			country="Saudi Arabia",
			custom_building_number="1234",
			custom_area="Aqrabiyah",
			custom_additional_number=number,
		)

	def _doc(self):
		# Built from the class directly: the override is no longer registered (row 28 was closed by
		# the client on 2026-10-15), so `frappe.new_doc` returns the upstream class.
		return zatca_buyer.YHTSalesInvoiceAdditionalFields({"doctype": "Sales Invoice Additional Fields"})

	def test_the_class_is_ours_and_still_the_upstream_one(self):
		doc = self._doc()
		self.assertIsInstance(doc, zatca_buyer.YHTSalesInvoiceAdditionalFields)
		self.assertIsInstance(doc, zatca_buyer._base_class())

	def test_a_four_digit_number_is_sent(self):
		doc = self._doc()
		doc._set_buyer_address(self._address("9581"))
		self.assertEqual(doc.buyer_additional_number, "9581")
		self.assertEqual(doc.buyer_building_number, "1234")  # the rest of upstream still ran

	def test_anything_else_is_empty_never_a_sentence(self):
		for bad in ("", None, "12", "12345", "abcd", " 12 3"):
			with self.subTest(value=bad):
				doc = self._doc()
				doc._set_buyer_address(self._address(bad))
				self.assertEqual(doc.buyer_additional_number, "")

	def test_whitespace_around_a_good_number_is_trimmed(self):
		doc = self._doc()
		doc._set_buyer_address(self._address(" 9581 "))
		self.assertEqual(doc.buyer_additional_number, "9581")

	def test_with_the_switch_off_upstream_behaviour_is_untouched(self):
		with _off("oct11_r28_zatca_additional_number"):
			doc = self._doc()
			doc._set_buyer_address(self._address("9581"))
			self.assertEqual(doc.buyer_additional_number, "not available for now")

	def test_the_override_is_not_registered_any_more(self):
		"""Row 28 was closed by the client on 2026-10-15; a class swap is active whenever hooks reload,
		whatever its switch says (the 2026-10-14 ZATCA queueing incident), so it stays unregistered
		until it is decided again. It was a class override and not a doc_event on purpose: ksa_compliance
		builds the XML inside its own `before_insert`."""
		hooks = frappe.get_hooks("override_doctype_class", app_name="yht_custom") or {}
		self.assertNotIn("Sales Invoice Additional Fields", hooks)
		events = frappe.get_hooks("doc_events", app_name="yht_custom") or {}
		self.assertNotIn("Sales Invoice Additional Fields", events)

	def test_the_additional_number_helper_never_raises_on_a_odd_address(self):
		self.assertEqual(zatca_buyer.additional_number(object()), "")
		self.assertEqual(zatca_buyer.additional_number(frappe._dict()), "")


# ------------------------------------------------------------------- row 29


class TestBranchPurchaseOrder(FrappeTestCase):
	def test_the_two_roles_may_raise_but_not_approve(self):
		from yht_custom.setup import BRANCH_MANAGER_ROLE, BRANCH_USER_ROLE

		branch_purchase_order.setup_branch_purchase_order()
		for role in (BRANCH_USER_ROLE, BRANCH_MANAGER_ROLE):
			row = frappe.db.get_value(
				"Custom DocPerm",
				{"parent": "Purchase Order", "role": role, "permlevel": 0},
				["read", "write", "create", "submit", "cancel", "delete", "amend"],
				as_dict=True,
			)
			self.assertTrue(row, role)
			self.assertEqual((row.read, row.write, row.create), (1, 1, 1), role)
			self.assertEqual((row.submit, row.cancel, row.delete, row.amend), (0, 0, 0, 0), role)

	def test_the_step_is_idempotent(self):
		branch_purchase_order.setup_branch_purchase_order()
		branch_purchase_order.setup_branch_purchase_order()
		self.assertEqual(
			frappe.db.count("Custom DocPerm", {"parent": "Purchase Order", "role": "Branch User"}), 1
		)

	def test_the_list_is_scoped_to_the_branch_when_on(self):
		clause = branch_purchase_order.purchase_order_query(BRANCH_USER)
		if not frappe.db.exists("User", BRANCH_USER):
			self.skipTest("branch test user not present")
		self.assertIn("`tabPurchase Order`", clause)
		self.assertIn("IN (", clause)

	def test_the_list_is_untouched_when_off(self):
		with _off("oct11_r29_branch_purchase_order"):
			self.assertEqual(branch_purchase_order.purchase_order_query(BRANCH_USER), "")
			self.assertIn("skipped", branch_purchase_order.setup_branch_purchase_order())

	def test_the_filter_is_registered_as_a_permission_query(self):
		hooks = frappe.get_hooks("permission_query_conditions", app_name="yht_custom") or {}
		entry = hooks.get("Purchase Order")
		self.assertIn("yht_custom.branch_purchase_order.purchase_order_query", str(entry))

	def test_branch_guard_already_covers_purchase_order_writes(self):
		events = frappe.get_hooks("doc_events", app_name="yht_custom") or {}
		validate = events.get("Purchase Order", {}).get("validate")
		validate = validate if isinstance(validate, list) else [validate]
		self.assertIn("yht_custom.branch_guard.validate_branch_scope", validate)

	def test_a_branch_user_can_create_but_not_submit_a_purchase_order(self):
		if not frappe.db.exists("User", BRANCH_USER):
			self.skipTest("branch test user not present")
		branch_purchase_order.setup_branch_purchase_order()
		frappe.clear_cache(user=BRANCH_USER)
		self.assertTrue(frappe.has_permission("Purchase Order", "create", user=BRANCH_USER))
		self.assertFalse(frappe.has_permission("Purchase Order", "submit", user=BRANCH_USER))
		self.assertFalse(frappe.has_permission("Purchase Order", "delete", user=BRANCH_USER))

	def test_the_dashboard_tile_and_the_allow_list_name_the_same_doctype(self):
		tile = _source("yht_custom/page/yht_dashboard/yht_dashboard.js")
		allow = _source("public/js/branch_user_restrict.js")
		self.assertIn('doctype: "Purchase Order"', tile)
		self.assertIn('ALLOWED_DOCTYPES.push("Purchase Order")', allow)


# ------------------------------------------------------------------- row 36


class TestBranchPrintFormat(FrappeTestCase):
	def _print_format(self, doctype, enabled=True):
		name = frappe.db.get_value("Print Format", {"doc_type": doctype, "disabled": 0 if enabled else 1}, "name")
		if not name:
			self.skipTest(f"no {'enabled' if enabled else 'disabled'} Print Format for {doctype}")
		return name

	def _doc(self, *rows):
		return frappe._dict(
			print_format=[
				frappe._dict(idx=i + 1, document_type=d, print_format=p) for i, (d, p) in enumerate(rows)
			]
		)

	def test_a_good_row_passes(self):
		branch_print_format.validate_rows(
			self._doc(("Sales Invoice", self._print_format("Sales Invoice")))
		)

	def test_a_format_built_for_another_doctype_is_refused(self):
		wrong = self._print_format("Delivery Note")
		with self.assertRaises(frappe.ValidationError):
			branch_print_format.validate_rows(self._doc(("Sales Invoice", wrong)))

	def test_a_missing_format_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			branch_print_format.validate_rows(self._doc(("Sales Invoice", "No Such Format ZQX")))

	def test_a_document_type_listed_twice_is_refused(self):
		name = self._print_format("Sales Invoice")
		with self.assertRaises(frappe.ValidationError):
			branch_print_format.validate_rows(self._doc(("Sales Invoice", name), ("Sales Invoice", name)))

	def test_a_disabled_format_is_refused(self):
		name = self._print_format("Quotation", enabled=False)
		with self.assertRaises(frappe.ValidationError):
			branch_print_format.validate_rows(self._doc(("Quotation", name)))

	def test_the_branch_users_rows_reach_boot_and_nobody_elses(self):
		if not frappe.db.exists("User", BRANCH_USER):
			self.skipTest("branch test user not present")
		config = frappe.db.get_value("Branch Configuration User", {"user": BRANCH_USER}, "parent")
		if not config:
			self.skipTest("branch test user has no Branch Configuration")
		name = self._print_format("Sales Invoice")
		frappe.get_doc(
			{
				"doctype": "Branch Configuration Print Format",
				"parent": config,
				"parenttype": "Branch Configuration",
				"parentfield": "print_format",
				"document_type": "Sales Invoice",
				"print_format": name,
				"idx": 99,
			}
		).db_insert()
		self.assertEqual(branch_print_format.formats_for_user(BRANCH_USER).get("Sales Invoice"), name)
		self.assertEqual(branch_print_format.formats_for_user("Administrator"), {})
		self.assertEqual(branch_print_format.formats_for_user("Guest"), {})

	def test_boot_is_empty_when_the_switch_is_off(self):
		with _off("oct11_r36_branch_print_format"):
			self.assertEqual(branch_print_format.boot_value(), {})

	def test_the_script_only_moves_the_preselection(self):
		source = _source("public/js/branch_print_format.js")
		self.assertIn("frm.meta.default_print_format", source)
		self.assertNotIn("frappe.set_route", source)
		self.assertIn("yht_branch_print_formats", _source("boot.py"))

	def test_the_table_is_on_branch_configuration(self):
		meta = frappe.get_meta("Branch Configuration")
		field = meta.get_field("print_format")
		self.assertEqual(field.fieldtype, "Table")
		self.assertEqual(field.options, "Branch Configuration Print Format")
		self.assertTrue(frappe.db.exists("DocType", "Branch Configuration Print Format"))
