# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""The remaining change requests from the client meeting of 2026-09-23.

CR-001 SPL address port · CR-002 district · CR-003 Address tab split ·
CR-004/005 print heading · CR-006 branch warehouse · CR-007 essentials-first ·
CR-008 SO/SI on the note · CR-012 expense classification · CR-013 list columns ·
CR-014 Unified Number · CR-015 remarks on the front page · CR-020 report groups ·
CR-021 Purchase Order print.

Written against the COMPLAINT, not against the configuration meant to produce it.
Two of these items existed as configuration and were still broken in production:
`select_print_heading` was filled on 1,906 Delivery Notes and never reached the
page, and `custom_is_expense_invoice` was 0 on every one of 3,614 Purchase
Invoices while 384 carried the expense series.
"""

import json
import os

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import features
from yht_custom.address_district import classify
from yht_custom.branch_defaults import WAREHOUSE_DOCTYPES
from yht_custom.dn_links import FIELDS as DN_LINK_FIELDS
from yht_custom.dn_links import _joined
from yht_custom.expense_invoice import EXPENSE_SERIES, _is_expense_series
from yht_custom.field_layout import CUSTOM_FIELD_MOVES, FIELD_MOVES, FIELD_ORDER
from yht_custom.list_columns import CLEAR_IN_LIST_VIEW, LIST_COLUMNS
from yht_custom.other_remarks import ANCHORS as REMARKS_ANCHORS
from yht_custom.print_heading import (
	ARABIC,
	DEFAULTS,
	LEGACY_TITLES,
	PRINT_AS,
	default_heading,
	english,
	yht_print_heading,
)
from yht_custom.report_groups import GROUPS
from yht_custom.unified_number import PATTERN as UNIFIED_PATTERN

APP = frappe.get_app_path("yht_custom")


def _read(*parts):
	with open(os.path.join(APP, *parts), encoding="utf-8") as handle:
		return handle.read()


class TestTheFeatureSwitch(FrappeTestCase):
	"""The thing that makes "deploy to UAT first" expressible on a shared bench."""

	def test_an_unknown_switch_raises_rather_than_reading_false(self):
		"""A typo must not be indistinguishable from "off on purpose"."""
		with self.assertRaises(KeyError):
			features.enabled("cr_999_does_not_exist")

	def test_every_switch_named_in_code_is_declared(self):
		"""Grep the app for `features.enabled("…")` and check each name is known.

		This is the guard that makes the raise above useful: without it a new call
		site can introduce a name nobody declared and the only symptom is a deploy
		that appears to do nothing.
		"""
		import re

		used = set()
		for root, _dirs, files in os.walk(APP):
			if "node_modules" in root or "/tests" in root:
				continue
			for filename in files:
				if not filename.endswith(".py"):
					continue
				with open(os.path.join(root, filename), encoding="utf-8") as handle:
					used |= set(re.findall(r'features\.enabled\(\s*"([^"]+)"', handle.read()))

		self.assertTrue(used, "no feature switch call sites found — the grep is wrong")
		self.assertEqual(used - set(features.KNOWN), set())

	def test_the_js_switch_name_matches_a_declared_one(self):
		"""`address.js` reads the list out of the boot payload by literal name."""
		self.assertIn("cr_001_spl_address", _read("public", "js", "address.js"))
		self.assertIn("cr_001_spl_address", features.KNOWN)


class TestCr001TheSplScriptIsPorted(FrappeTestCase):
	def test_the_parser_puts_the_district_where_zatca_reads_it(self):
		"""`parts[3]` -> `custom_area`, which is what settles CR-002.

		Asserted on the SOURCE because this is the client's own mechanism and the
		reason `custom_area` — not `county` — is authoritative.
		"""
		source = _read("public", "js", "address.js")
		self.assertIn("custom_area: parts[3]", source)

	def test_it_is_inert_until_the_switch_is_on(self):
		source = _read("public", "js", "address.js")
		self.assertIn("if (!yht.address.enabled())", source)

	def test_the_patch_disables_exactly_the_two_scripts_it_replaces(self):
		from yht_custom.patches.disable_ported_address_scripts import PORTED

		self.assertEqual(set(PORTED), {"Get SPL Full Address", "Address Fetching"})


class TestCr002TheDistrict(FrappeTestCase):
	"""Every case below is a real value read off the client's own data."""

	def test_a_county_that_is_just_the_city_is_not_a_district(self):
		for county, city in (("Dammam ", "Dammam"), ("ALKHOBAR", "AL KHOBAR"), ("RIYADH", "RIYADH")):
			with self.subTest(county=county):
				self.assertEqual(classify(county, city), ("city_only", ""))

	# A spelling variant of the city must collapse too, or every KHUBAR row
	# would be copied into the district cell as the city.
	def test_the_khobar_spellings_all_collapse(self):
		bucket, value = classify("AL KHUBAR ASH SHAMALIYAH", "AL KHOBAR")
		self.assertEqual((bucket, value), ("district", "ASH SHAMALIYAH"))

	def test_the_literal_string_null_is_junk(self):
		self.assertEqual(classify("NULL", "DAMMAM"), ("junk", ""))

	def test_a_major_city_is_never_a_district_however_dirty_the_city_column_is(self):
		"""`CU0341-Billing` carries county "Dammam" and city " Industrial City",
		so the row-local comparison alone stored Dammam as the district."""
		self.assertEqual(classify("Dammam", " Industrial City"), ("city_only", ""))
		self.assertEqual(classify("RIYADH", ""), ("city_only", ""))

	def test_a_street_is_not_a_district(self):
		self.assertEqual(classify("PRINCE TALAL STREET", "AL KHOBAR"), ("street", ""))

	def test_a_trailing_dist_is_stripped_but_the_district_survives(self):
		self.assertEqual(classify("AL AZIZIYAH DIST.", "AL KHOBAR"), ("district", "AL AZIZIYAH"))

	def test_the_stored_value_keeps_its_own_spacing(self):
		"""Squashing is a COMPARISON device. Storing "ASHSHAMALIYAH" would be a new
		data-quality problem in place of the old one."""
		_bucket, value = classify("ALKHOBAR ASH SHAMALIYAH", "AL KHOBAR")
		self.assertEqual(value, "ASH SHAMALIYAH")

	def test_the_print_helper_reads_the_legacy_column_as_a_fallback(self):
		source = _read("print_helpers.py")
		self.assertIn("_derive_district(result, row)", source)
		self.assertIn('"county"', source)

	def test_custom_area_is_never_overwritten_by_the_backfill(self):
		source = _read("address_district.py")
		self.assertIn('if cstr(row.custom_area).strip():', source)


class TestCr003TheAddressFirstTab(FrappeTestCase):
	"""The complaint: required fields sat behind a tab nobody had opened."""

	def test_the_declared_order_exists(self):
		self.assertIn("Address", FIELD_ORDER)

	def test_the_declared_order_names_nothing_that_does_not_exist(self):
		"""A name in the declared order that no site carries logs a skip on EVERY
		migrate, which is how real diagnostics get lost in noise. Every entry is
		either a standard field, one of ours, or created by `STRUCTURAL_FIELDS`."""
		meta_fields = {f.fieldname for f in frappe.get_meta("Address").fields}
		self.assertEqual(set(FIELD_ORDER["Address"]) - meta_fields, set())

	def test_the_paste_box_is_ours_too(self):
		"""CR-001's parser fires on it, and it existed on the live site only."""
		self.assertIsNotNone(frappe.get_meta("Address").get_field("custom_national_address_full_data"))

	def test_the_tab_break_is_ours_rather_than_a_hand_edit(self):
		"""It existed on the live site only, added through Customize Form, so the
		item could not be verified anywhere else until this module created it."""
		from yht_custom.field_layout import STRUCTURAL_FIELDS

		self.assertEqual(STRUCTURAL_FIELDS["Address"][0]["fieldtype"], "Tab Break")
		self.assertIsNotNone(frappe.get_meta("Address").get_field("custom_more_details"))

	def test_the_live_form_actually_splits_there(self):
		"""The assertion the CR is about: nothing mandatory behind the tab."""
		order = [f.fieldname for f in frappe.get_meta("Address").fields]
		tab = order.index("custom_more_details")
		for fieldname in ("pincode", "city", "country", "address_type", "custom_short_address"):
			with self.subTest(field=fieldname):
				self.assertLess(order.index(fieldname), tab)

	def test_every_mandatory_field_is_ahead_of_the_tab_break(self):
		order = FIELD_ORDER["Address"]
		tab = order.index("custom_more_details")
		for fieldname in ("custom_short_address", "custom_additional_number", "pincode", "city", "country", "address_type"):
			with self.subTest(field=fieldname):
				self.assertLess(order.index(fieldname), tab)

	def test_the_arabic_block_is_behind_it(self):
		order = FIELD_ORDER["Address"]
		tab = order.index("custom_more_details")
		for fieldname in ("custom_area_arabic", "custom_city_arabic", "custom_country_arabic"):
			with self.subTest(field=fieldname):
				self.assertGreater(order.index(fieldname), tab)

	def test_it_names_each_field_once(self):
		order = FIELD_ORDER["Address"]
		self.assertEqual(len(order), len(set(order)))

	def test_only_one_mechanism_orders_a_doctype(self):
		"""The pairwise pass runs after the declared one, ON THE SAME LIST — so a
		doctype in both would have its declared order silently rewritten. It did:
		Postal Code · City · Country were hoisted above District on every migrate.
		"""
		self.assertEqual(set(FIELD_ORDER) & set(FIELD_MOVES), set())

	def test_the_left_column_reads_the_way_the_client_asked(self):
		order = FIELD_ORDER["Address"]
		sequence = [
			"custom_short_address",
			"address_type",
			"custom_building_number",
			"address_line1",
			"custom_additional_number",
			"custom_area",
			"pincode",
			"city",
			"country",
		]
		positions = [order.index(f) for f in sequence]
		self.assertEqual(positions, sorted(positions), "the client's sequence is not in order")


class TestCr004AndCr005ThePrintHeading(FrappeTestCase):
	def test_the_field_is_standard_and_already_editable_after_submit(self):
		"""CR-005 needs no new field and no new bulk tool — this is why."""
		for doctype in DEFAULTS:
			with self.subTest(doctype=doctype):
				field = frappe.get_meta(doctype).get_field("select_print_heading")
				self.assertIsNotNone(field)
				self.assertTrue(field.allow_on_submit)

	def test_a_return_gets_the_return_heading(self):
		note = frappe.new_doc("Delivery Note")
		note.is_return = 1
		self.assertEqual(default_heading(note), "Delivery Note Return")
		note.is_return = 0
		self.assertEqual(default_heading(note), "Delivery Note")

	def test_a_credit_note_is_not_called_a_sales_invoice(self):
		invoice = frappe.new_doc("Sales Invoice")
		invoice.is_return = 1
		self.assertEqual(default_heading(invoice), "Credit Note")

	def test_an_expense_invoice_prints_as_one(self):
		invoice = frappe.new_doc("Purchase Invoice")
		invoice.custom_is_expense_invoice = 1
		self.assertEqual(default_heading(invoice), "Expenses Invoice")

	def test_every_default_heading_has_an_arabic_twin(self):
		for doctype, (forward, returned) in DEFAULTS.items():
			for heading in (forward, returned):
				if heading:
					with self.subTest(doctype=doctype, heading=heading):
						self.assertTrue(ARABIC.get(heading))

	def test_every_print_as_option_resolves(self):
		"""A Select option with no Arabic prints a title in one language only."""
		for doctype, options in PRINT_AS.items():
			for option in options:
				with self.subTest(doctype=doctype, option=option):
					self.assertIn(option, ARABIC, f"{option} has no Arabic")

	def test_the_quotation_still_says_quotation(self):
		"""The RECORD is 'Sales Quotation'; the page says what the incumbent said."""
		self.assertEqual(english("Sales Quotation"), "QUOTATION")

	def test_the_templates_stopped_hardcoding_the_title(self):
		for template in ("quotation.html", "sales_order.html", "proforma_invoice.html", "purchase_order.html"):
			with self.subTest(template=template):
				source = _read("templates", "includes", "katc", template)
				self.assertIn("katc_heading.en", source)
				self.assertNotIn('katc-title">SALES ORDER<', source)
				self.assertNotIn('katc-title">PROFORMA INVOICE<', source)

	def test_the_arabic_column_follows_the_print_language(self):
		for template in ("quotation.html", "sales_order.html", "purchase_order.html"):
			with self.subTest(template=template):
				source = _read("templates", "includes", "katc", template)
				self.assertIn('yht_print_lang() == "ar"', source)

	def test_the_jinja_methods_are_registered(self):
		"""An unregistered method is an exception on every page that renders."""
		methods = frappe.get_hooks("jinja", app_name="yht_custom")["methods"]
		self.assertIn("yht_custom.print_heading.yht_print_heading", methods)
		self.assertIn("yht_custom.print_heading.yht_print_lang", methods)

	def test_the_hook_doctypes_match_the_defaults(self):
		"""hooks.py repeats the list literally because it is read before import."""
		registered = {
			doctype
			for doctype, events in frappe.get_hooks("doc_events", app_name="yht_custom").items()
			if "yht_custom.print_heading.set_print_heading"
			in (events.get("before_save") or [])
		}
		self.assertEqual(registered, set(DEFAULTS))

	def test_a_chosen_heading_is_never_overwritten(self):
		"""CR-005 is a bulk CORRECTION; re-deriving would undo it on the next save."""
		self.assertIn("if cstr(doc.get(\"select_print_heading\")).strip():", _read("print_heading.py"))


class TestCr006TheBranchWarehouse(FrappeTestCase):
	def test_quotation_is_in_scope_but_payment_entry_is_not(self):
		self.assertIn("Quotation", WAREHOUSE_DOCTYPES)
		self.assertNotIn("Payment Entry", WAREHOUSE_DOCTYPES)
		self.assertNotIn("Journal Entry", WAREHOUSE_DOCTYPES)

	def test_it_corrects_a_foreign_warehouse_but_leaves_one_of_the_branchs_own(self):
		"""The rule that separates this from the cost-center handler it copies."""
		source = _read("branch_defaults.py")
		self.assertIn('not in allowed', source)
		self.assertIn("warehouses[0]", source)

	def test_it_is_registered_after_the_cost_center_handler(self):
		events = frappe.get_hooks("doc_events", app_name="yht_custom")["Sales Invoice"]["before_validate"]
		self.assertLess(
			events.index("yht_custom.branch_defaults.apply_branch_defaults"),
			events.index("yht_custom.branch_defaults.apply_branch_warehouse"),
		)

	def test_it_is_behind_a_switch(self):
		self.assertIn('features.enabled("cr_006_branch_warehouse")', _read("branch_defaults.py"))

	def test_the_picker_is_scoped_and_not_only_the_saved_value(self):
		"""Acceptance #2, and the first version missed it. Correcting the value on
		`before_validate` alone leaves the dropdown offering every warehouse on the
		site and then silently replacing the operator's choice on save."""
		js = _read("public", "js", "branch_warehouse.js")
		self.assertIn('frm.set_query("set_warehouse"', js)
		self.assertIn('frm.set_query("warehouse", "items"', js)
		self.assertIn("branch_warehouse.js", _read("hooks.py"))

	def test_the_list_reaches_the_form_through_boot(self):
		"""`set_query` is registered while the form is built and has no moment to
		fetch, so the list has to be in the boot payload."""
		self.assertIn("yht_branch_warehouses", _read("boot.py"))
		self.assertIn("frappe.boot.yht_branch_warehouses", _read("public", "js", "branch_warehouse.js"))

	def test_an_empty_list_means_do_not_filter(self):
		"""A bypass user, or a user on no branch, keeps the full picker — the same
		rule `_branch_series_rows` follows rather than guessing a branch."""
		js = _read("public", "js", "branch_warehouse.js")
		self.assertIn("if (!yht.branch_warehouse.list().length) return;", js)


class TestCr006TheWarehouseRulesBehave(FrappeTestCase):
	"""Acceptance #3 — mirror the cost-center override tests, i.e. exercise the
	handler on a document rather than asserting it is registered."""

	def setUp(self):
		from yht_custom import branch_defaults

		self.bd = branch_defaults
		frappe.conf.yht_features = ["all"]
		self._config = branch_defaults._user_branch_config
		self._list = branch_defaults._branch_warehouses
		self._bypass = branch_defaults._is_bypass
		branch_defaults._user_branch_config = lambda user=None: "TEST-CONFIG"
		branch_defaults._branch_warehouses = lambda config: ["Branch A - K", "Branch B - K"]
		branch_defaults._is_bypass = lambda user=None: False

	def tearDown(self):
		self.bd._user_branch_config = self._config
		self.bd._branch_warehouses = self._list
		self.bd._is_bypass = self._bypass
		frappe.conf.pop("yht_features", None)

	def _note(self, header, row):
		doc = frappe.new_doc("Delivery Note")
		doc.set_warehouse = header
		doc.append("items", {"item_code": None, "warehouse": row, "qty": 1})
		return doc

	def test_a_blank_warehouse_is_filled_with_the_branchs_first(self):
		doc = self._note("", "")
		self.bd.apply_branch_warehouse(doc)
		self.assertEqual(doc.set_warehouse, "Branch A - K")
		self.assertEqual(doc.items[0].warehouse, "Branch A - K")

	def test_a_warehouse_that_is_not_the_branchs_is_corrected(self):
		doc = self._note("Somebody Else - X", "Somebody Else - X")
		self.bd.apply_branch_warehouse(doc)
		self.assertEqual(doc.set_warehouse, "Branch A - K")
		self.assertEqual(doc.items[0].warehouse, "Branch A - K")

	def test_one_of_the_branchs_OWN_other_warehouses_is_left_alone(self):
		"""The rule that separates this from the cost-center handler it copies: a
		branch legitimately has several warehouses and a transfer between two of
		them must survive."""
		doc = self._note("Branch B - K", "Branch B - K")
		self.bd.apply_branch_warehouse(doc)
		self.assertEqual(doc.set_warehouse, "Branch B - K")
		self.assertEqual(doc.items[0].warehouse, "Branch B - K")

	def test_nothing_happens_with_the_switch_off(self):
		frappe.conf.pop("yht_features", None)
		doc = self._note("Somebody Else - X", "Somebody Else - X")
		self.bd.apply_branch_warehouse(doc)
		self.assertEqual(doc.set_warehouse, "Somebody Else - X")


class TestCr020TheBranchUserCanStillReachTheReports(FrappeTestCase):
	"""Acceptance: "confirm the existing branch-user single-permission gate on this
	event is unaffected"."""

	def test_every_report_in_the_workspace_resolves(self):
		links = [
			l.link_to
			for l in frappe.get_doc("Workspace", "KATC Reports").links
			if l.type == "Link"
		]
		self.assertTrue(links)
		missing = [r for r in links if not frappe.db.exists("Report", r)]
		self.assertEqual(missing, [], "a link to a report that does not exist breaks the whole page")

	def test_the_existing_role_gate_survived_the_regroup(self):
		"""🔴 THE GATE IS SUPPOSED TO BE THERE. The criterion says "confirm the
		existing branch-user permission gate on this event is unaffected" — the
		fault mode is losing it, not having it. This test asserted `roles == []`
		first, which is the inverse of the requirement and would have passed only
		if `setup_report_groups` had stripped the gate.

		Measured: the workspace carries Branch User, Branch Manager, Accounts
		Manager, Accounts User, Sales Manager and Stock Manager, and regrouping
		the links left all six alone."""
		ws = frappe.get_doc("Workspace", "KATC Reports")
		self.assertTrue(ws.public, "the workspace stopped being public")
		roles = {r.role for r in (ws.get("roles") or [])}
		self.assertIn("Branch User", roles, f"the branch-user gate is gone: {sorted(roles)}")
		self.assertGreaterEqual(len(roles), 6, f"the gate narrowed to {sorted(roles)}")

	def test_the_regroup_touches_links_and_nothing_else(self):
		"""Why the gate survives: the step rewrites `doc.links` only."""
		source = _read("report_groups.py")
		self.assertIn("doc.links = []", source)
		self.assertNotIn("doc.roles", source)
		self.assertNotIn("doc.public", source)


class TestCr007EssentialsFirst(FrappeTestCase):
	def test_the_sales_order_purchase_order_number_moves_up(self):
		self.assertIn(("po_no", "tax_id"), FIELD_MOVES["Sales Order"])
		self.assertIn(("po_date", "po_no"), FIELD_MOVES["Sales Order"])

	def test_the_delivery_note_customer_po_is_on_the_front_page(self):
		"""Production had this through a hand edit and UAT did not, so it is
		declared: CR-008 and CR-015 both anchor on `po_date`."""
		self.assertIn(("po_no", "tax_id"), FIELD_MOVES["Delivery Note"])
		order = [f.fieldname for f in frappe.get_meta("Delivery Note").fields]
		self.assertLess(order.index("po_no"), order.index("items"))

	def test_the_quotation_pairs_all_name_fields_it_has(self):
		meta = frappe.get_meta("Quotation")
		for fieldname, anchor in FIELD_MOVES["Quotation"]:
			with self.subTest(pair=(fieldname, anchor)):
				self.assertIsNotNone(meta.get_field(fieldname), fieldname)
				self.assertIsNotNone(meta.get_field(anchor), anchor)


class TestCr008TheNumbersOnTheNote(FrappeTestCase):
	def test_both_fields_exist_on_the_front_page(self):
		meta = frappe.get_meta("Delivery Note")
		items = [f.fieldname for f in meta.fields].index("items")
		for fieldname in DN_LINK_FIELDS:
			with self.subTest(field=fieldname):
				field = meta.get_field(fieldname)
				self.assertIsNotNone(field, f"{fieldname} not provisioned")
				self.assertTrue(field.read_only)
				self.assertLess([f.fieldname for f in meta.fields].index(fieldname), items)

	def test_the_joined_value_can_never_overflow_the_column(self):
		"""`Data` is 140 characters and an overflow raises DataError on save."""
		value = _joined([f"KSSO-26-{n:04d}" for n in range(60)])
		self.assertLessEqual(len(value), 140)
		self.assertTrue(value.endswith("…"))

	def test_it_is_distinct_and_keeps_its_order(self):
		self.assertEqual(_joined(["B", "A", "B", "", None, "A"]), "B, A")

	def test_the_invoice_end_is_wired_to_both_submit_and_cancel(self):
		events = frappe.get_hooks("doc_events", app_name="yht_custom")["Sales Invoice"]
		for event in ("on_submit", "on_cancel"):
			with self.subTest(event=event):
				self.assertIn("yht_custom.dn_links.refresh_from_invoice", events[event] or [])

	def test_it_never_saves_the_note_and_never_bumps_its_timestamp(self):
		"""A display mirror must not make every open copy of the note stale, and
		must never be written through a save on a submitted document."""
		source = _read("dn_links.py")
		self.assertIn("update_modified=False", source)
		self.assertNotIn(".save(", source)


class TestCr012TheExpenseClassification(FrappeTestCase):
	def test_the_marker_matches_every_expense_series_and_no_purchase_one(self):
		for series in (
			EXPENSE_SERIES,
			"KSEPI-25-.####",
			".{custom_company_series_abbr}.EPI-24-.####",
			"..{custom_company_series_abbr}.EPI-25-.####",
		):
			with self.subTest(series=series):
				self.assertTrue(_is_expense_series(series))

		for series in (
			"KSPI-.YY.-.####",
			"KSPR-.YY.-.####",
			"KSXI-.YY.-.####",
			".{custom_company_series_abbr}.PI-26-.####",
			".{custom_company_series_abbr}.PR-25-.####",
		):
			with self.subTest(series=series):
				self.assertFalse(_is_expense_series(series))

	def test_the_flag_is_derived_from_the_series_on_a_new_invoice(self):
		frappe.conf.yht_features = ["cr_012_expense_backfill"]
		try:
			from yht_custom.expense_invoice import derive_expense_flag

			invoice = frappe.new_doc("Purchase Invoice")
			invoice.naming_series = EXPENSE_SERIES
			derive_expense_flag(invoice)
			self.assertEqual(invoice.custom_is_expense_invoice, 1)
		finally:
			frappe.conf.pop("yht_features", None)

	def test_it_never_clears_a_flag_somebody_set(self):
		frappe.conf.yht_features = ["cr_012_expense_backfill"]
		try:
			from yht_custom.expense_invoice import derive_expense_flag

			invoice = frappe.new_doc("Purchase Invoice")
			invoice.naming_series = "KSPI-.YY.-.####"
			invoice.custom_is_expense_invoice = 1
			derive_expense_flag(invoice)
			self.assertEqual(invoice.custom_is_expense_invoice, 1)
		finally:
			frappe.conf.pop("yht_features", None)

	def test_it_runs_before_the_shaping_step(self):
		events = frappe.get_hooks("doc_events", app_name="yht_custom")["Purchase Invoice"]["before_validate"]
		self.assertLess(
			events.index("yht_custom.expense_invoice.derive_expense_flag"),
			events.index("yht_custom.expense_invoice.before_validate"),
		)

	def test_the_standard_filter_comes_back(self):
		""""Correct in bulk" needs a filtered list to run the bulk edit from."""
		self.assertIn("_restore_expense_standard_filter", _read("expense_invoice.py"))


class TestCr013TheListColumns(FrappeTestCase):
	def test_it_never_sets_title_field_to_name(self):
		"""That emptied all eight lists on this very site. See the module docstring."""
		for doctype, (title_field, _columns) in LIST_COLUMNS.items():
			with self.subTest(doctype=doctype):
				self.assertNotEqual(title_field, "name")
				self.assertIsNotNone(frappe.get_meta(doctype).get_field(title_field))

	def test_the_title_column_is_the_one_being_cleared(self):
		for doctype in LIST_COLUMNS:
			with self.subTest(doctype=doctype):
				self.assertIn("title", CLEAR_IN_LIST_VIEW[doctype])

	def test_it_is_behind_a_switch_because_the_doctype_is_a_guess(self):
		self.assertIn('features.enabled("cr_013_list_columns")', _read("list_columns.py"))

	def test_columns_go_through_list_view_settings_not_in_list_view(self):
		"""The acceptance criterion says "via standard List View Settings, not a
		hidden hack". `in_list_view` is a SCHEMA flag that also drives the link
		search preview, quick entry and the report view — bending it to pick list
		columns changes three other screens as a side effect."""
		source = _read("list_columns.py")
		code = "\n".join(
			line for line in source.splitlines()
			if not line.strip().startswith(("#", "🔴", "`")) 
		)
		self.assertIn("List View Settings", source)
		self.assertNotIn('"in_list_view", "1"', code)

	def test_the_stale_property_setters_are_cleaned_up(self):
		"""A Property Setter is a row, not a line of code: the first version's
		rows keep working after the code changed unless something deletes them."""
		from yht_custom.list_columns import drop_stale_in_list_view_setters

		self.assertTrue(callable(drop_stale_in_list_view_setters))
		self.assertIn("drop_stale_in_list_view_setters", _read("patches", "backfill_meeting_0923_data.py"))

	def test_no_in_list_view_setter_survives_for_the_columns_we_chose(self):
		"""Checked against the database, not the source."""
		from yht_custom.list_columns import LIST_COLUMNS

		for doctype, (_title, columns) in LIST_COLUMNS.items():
			stale = frappe.get_all(
				"Property Setter",
				filters={"doc_type": doctype, "property": "in_list_view", "field_name": ["in", list(columns)]},
				pluck="name",
			)
			with self.subTest(doctype=doctype):
				self.assertEqual(stale, [])


class TestCr014TheUnifiedNumber(FrappeTestCase):
	def test_the_field_exists_on_company(self):
		self.assertIsNotNone(frappe.get_meta("Company").get_field("custom_unified_number"))

	def test_the_shape_is_ten_digits_starting_with_seven(self):
		self.assertTrue(UNIFIED_PATTERN.match("7001234567"))
		for bad in ("1001234567", "700123456", "70012345678", "7ABC123456"):
			with self.subTest(value=bad):
				self.assertIsNone(UNIFIED_PATTERN.match(bad))

	def test_the_letterhead_is_unchanged_while_the_field_is_empty(self):
		"""Shippable without an answer from the client — that is the whole design."""
		from yht_custom.katc_letterhead import build_content, unified_number

		content = build_content()
		if unified_number():
			self.assertIn("Unified No.", content)
		else:
			self.assertNotIn("Unified No.", content)
			self.assertNotIn("الرقم الموحد", content)

	def test_the_arabic_line_carries_no_second_directional_span(self):
		"""Gotcha 45: two `dir="ltr"` boxes on one RTL line overlap in the PDF."""
		source = _read("katc_letterhead.py")
		self.assertIn('arabic_tail += f"<br>الرقم الموحد {unified}"', source)


class TestCr015TheRemarksBox(FrappeTestCase):
	def test_the_delivery_note_anchor_is_on_the_front_page(self):
		anchors = REMARKS_ANCHORS["Delivery Note"]
		self.assertEqual(anchors[0], "custom_sales_invoice_no")
		self.assertIn("po_date", anchors)

	def test_no_second_remarks_field_was_created(self):
		"""The client's complaint was duplicates. One field, moved."""
		fields = frappe.get_all(
			"Custom Field", filters={"dt": "Delivery Note", "fieldname": ["like", "%remark%"]}, pluck="fieldname"
		)
		self.assertEqual(sorted(fields), ["custom_other_remarks"])

	def test_it_is_positioned_by_its_own_anchor_not_by_a_replayed_move(self):
		"""`custom_other_remarks` is re-applied by our own `fixtures` hook, so
		`_apply_custom_field_moves` refuses to touch it — `other_remarks.ANCHORS`
		is the lever that actually wins, and listing it in both logs a skip on
		every migrate for nothing."""
		self.assertNotIn("custom_other_remarks", dict(CUSTOM_FIELD_MOVES["Delivery Note"]))

	def test_it_lands_on_the_front_page(self):
		order = [f.fieldname for f in frappe.get_meta("Delivery Note").fields]
		self.assertLess(order.index("custom_other_remarks"), order.index("items"))


class TestCr018TheGridSearchDropdown(FrappeTestCase):
	"""The CR was recorded as being about the COLUMN width. It is about the popup."""

	def _css(self):
		return _read("public", "css", "yht_custom.css")

	def test_frappes_own_rule_is_still_what_we_are_overriding(self):
		"""The premise, asserted against upstream rather than remembered.

		`min-width: 250px` on the listbox is WHY the popup ignores the column
		width. If a frappe upgrade drops or changes it, our override is sized
		against something that no longer exists and this says so.
		"""
		scss = os.path.join(
			frappe.get_app_path("frappe"), "public", "scss", "common", "awesomeplete.scss"
		)
		with open(scss, encoding="utf-8") as handle:
			source = handle.read()
		self.assertIn("min-width: 250px", source)
		self.assertIn("width: 100%", source)

	def test_the_override_is_scoped_to_the_grid(self):
		"""An ordinary form's link field already spans its column; the navbar
		search and the filter area would both look wrong at 520px."""
		css = self._css()
		self.assertIn(".form-grid .grid-static-col .awesomplete >", css)

	def test_every_selector_carries_the_body_class(self):
		"""This stylesheet reaches the client's live site on the pull, so ONE
		unscoped selector is enough to change the live desk. Checked per line,
		rather than by finding the good case somewhere in the file."""
		unscoped = [
			line.strip()
			for line in self._css().splitlines()
			if ".grid-static-col .awesomplete" in line
			and not line.strip().startswith(("*", "/*", "//"))
			and "body.yht-wide-grid-search" not in line
		]
		self.assertEqual(unscoped, [])

	def test_it_is_desktop_only(self):
		"""`grid.scss` clips `.form-grid-container` horizontally below `md`, so a
		520px popup would be cut off rather than overflow."""
		css = self._css()
		rule = css[css.index("CR-018") :]
		self.assertIn("@media (min-width: 768px)", rule)

	def test_the_width_clears_the_longest_item_name(self):
		"""75 characters at the dropdown's type. Sized on the data, not on taste."""
		css = self._css()
		self.assertIn("min-width: 520px", css)

	def test_the_switch_name_matches_a_declared_one(self):
		"""The grep test over Python cannot see this one — it is referenced only
		from JS, so its name is checked here instead."""
		js = _read("public", "js", "grid_search_width.js")
		self.assertIn("cr_018_grid_search_width", js)
		self.assertIn("cr_018_grid_search_width", features.KNOWN)
		self.assertIn("cr_018_grid_search_width", self._css())

	def test_the_class_is_written_after_boot_not_at_import_time(self):
		"""`frappe.boot` is empty when a desk bundle first evaluates, so reading
		the feature list at import silently gives an empty array for ever."""
		js = _read("public", "js", "grid_search_width.js")
		self.assertIn('$(document).on("app_ready startup"', js)

	def test_the_bundle_is_registered_and_the_stylesheet_cache_busted(self):
		"""Assets under /assets are served with no Cache-Control, so an unbumped
		`?v=` makes the deploy invisible to anyone already loaded."""
		hooks = _read("hooks.py")
		self.assertIn("js/grid_search_width.js?v=", hooks)
		self.assertNotIn("css/yht_custom.css?v=7", hooks)


class TestCr019TheRateDoubleClick(FrappeTestCase):
	"""Reported as "clicking Rate loads Price Assist". It is a DOUBLE click — and
	a double click on a number is how you select it to retype it."""

	def _js(self):
		return _read("public", "js", "price_assist.js")

	def test_the_shortcut_is_a_double_click_on_the_rate_cell(self):
		"""The mechanism, written down: the CR called it a 'direct-click path' and
		it is not one, which is why nobody could find it from the transcript."""
		js = self._js()
		self.assertIn("DOUBLE_CLICK_MS", js)
		self.assertIn("[data-fieldname=\"rate\"]", js)

	def test_it_bails_out_before_doing_any_dom_work(self):
		"""This listener runs on EVERY click in the desk, capture phase. With the
		switch on it must cost less than it does today, not more."""
		js = self._js()
		body = js[js.index("function (event) {") :]
		self.assertLess(
			body.index("rate_shortcut_disabled()"),
			body.index("closest("),
			"the feature check must come before the DOM walk",
		)

	def test_the_button_and_the_quiet_hint_are_untouched(self):
		"""'Keep only the button' — so the button, and the toast that blocks
		nothing, both stay."""
		js = self._js()
		self.assertIn('grid.add_custom_button(__("Price Assist")', js)
		self.assertIn("yht_custom.price.hint(frm, locals[cdt][cdn])", js)

	def test_the_dialog_stops_advertising_the_gesture_that_was_removed(self):
		"""The "Which line?" dialog told operators to double-click the Rate. With
		the shortcut gone that is an instruction to do something that no longer
		works — found by re-reading the acceptance criterion, not by a failure."""
		js = self._js()
		start = js.index("Which line?")
		end = js.index("primary_action_label", start)
		self.assertIn("rate_shortcut_disabled()", js[start:end])

	def test_the_switch_is_declared_and_the_bundle_cache_busted(self):
		js = self._js()
		self.assertIn("cr_019_no_rate_doubleclick", js)
		self.assertIn("cr_019_no_rate_doubleclick", features.KNOWN)
		self.assertNotIn("price_assist.js?v=6", _read("hooks.py"))


class TestCr020TheReportGroups(FrappeTestCase):
	def test_the_groups_are_the_clients_categories(self):
		labels = [label for label, _names in GROUPS]
		self.assertIn("Stock", labels)
		self.assertIn("Sales Statements", labels)

	def test_no_report_is_listed_twice(self):
		seen = []
		for _label, names in GROUPS:
			seen.extend(names)
		self.assertEqual(len(seen), len(set(seen)))

	def test_a_missing_report_is_dropped_rather_than_breaking_the_workspace(self):
		self.assertIn("def _existing(names)", _read("report_groups.py"))


class TestCr021ThePurchaseOrderPrint(FrappeTestCase):
	def test_the_format_record_points_at_the_template(self):
		record = json.loads(
			_read("yht_custom", "print_format", "katc_purchase_order", "katc_purchase_order.json")
		)
		self.assertEqual(record["doc_type"], "Purchase Order")
		self.assertIn("katc/purchase_order.html", record["html"])
		self.assertEqual(record["pdf_generator"], "wkhtmltopdf-shrink")

	def test_it_reuses_the_proven_frame(self):
		"""The three things that took two client-visible regressions to get right."""
		source = _read("templates", "includes", "katc", "purchase_order.html")
		self.assertIn('id="header-html"', source)
		self.assertIn("page-break-inside: auto !important", source)
		self.assertIn("yht_katc_spacer_pt()", source)

	def test_it_shows_the_transaction(self):
		"""The literal complaint about the incumbent: it "doesn't show the transaction"."""
		source = _read("templates", "includes", "katc", "purchase_order.html")
		for marker in ("doc.items", "row.qty", "row.rate", "row.amount", "grand_total"):
			with self.subTest(marker=marker):
				self.assertIn(marker, source)

	def test_the_supplier_vat_falls_back_to_the_master(self):
		source = _read("templates", "includes", "katc", "purchase_order.html")
		self.assertIn('yht_party_vat(doc, "supplier")', source)


class TestTheLivePrintDoesNotChangeUntilTheSwitchIsOn(FrappeTestCase):
	"""The shared bench, stated as an assertion.

	`apps/yht_custom` serves the client's live site and UAT out of ONE directory,
	and a template is read from disk on every render. Without these, pulling this
	work would change the live quotation print in the same instant — which is the
	one thing the client's own deploy rule forbids.
	"""

	def setUp(self):
		frappe.conf.pop("yht_features", None)

	def tearDown(self):
		frappe.conf.pop("yht_features", None)

	def test_the_quotation_keeps_its_single_line_title(self):
		doc = frappe.new_doc("Quotation")
		out = yht_print_heading(doc)
		self.assertEqual(out["en"], LEGACY_TITLES["Quotation"][0])
		self.assertEqual(out["ar"], "", "the old markup was ONE div, not a pair")

	def test_a_stored_heading_cannot_override_the_template_that_is_printing(self):
		"""Caught on UAT: the backfill stamped "Sales Quotation" onto 2,726
		quotations and every Proforma print then said QUOTATION."""
		frappe.conf.yht_features = ["all"]
		doc = frappe.new_doc("Quotation")
		doc.select_print_heading = "Sales Quotation"
		self.assertEqual(yht_print_heading(doc, "Proforma Invoice")["en"], "PROFORMA INVOICE")

	def test_the_proforma_is_told_what_it_is_by_the_template(self):
		"""`proforma_invoice.html` renders a QUOTATION document, so the doctype
		alone would title it 'Quotation'."""
		doc = frappe.new_doc("Quotation")
		self.assertEqual(yht_print_heading(doc, "Proforma Invoice")["en"], "PROFORMA INVOICE")

	def test_the_arabic_column_does_not_appear_by_itself(self):
		from yht_custom.print_heading import yht_print_lang

		frappe.local.lang = "ar"
		try:
			self.assertEqual(yht_print_lang(), "en")
		finally:
			frappe.local.lang = "en"

	def test_the_district_cell_stays_as_it_was(self):
		self.assertFalse(features.enabled("cr_002_district_fallback"))
		self.assertIn('enabled("cr_002_district_fallback")', _read("print_helpers.py"))

	def test_and_with_the_switch_on_every_axis_moves(self):
		frappe.conf.yht_features = ["all"]
		from yht_custom.print_heading import yht_print_lang

		doc = frappe.new_doc("Quotation")
		self.assertEqual(yht_print_heading(doc)["en"], "QUOTATION")
		self.assertEqual(yht_print_heading(doc)["ar"], ARABIC["Sales Quotation"])
		frappe.local.lang = "ar"
		try:
			self.assertEqual(yht_print_lang(), "ar")
		finally:
			frappe.local.lang = "en"
