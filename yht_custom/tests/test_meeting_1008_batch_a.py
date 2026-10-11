# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Batch A of the client meeting of 2026-10-08 — the "New Task" sheet.

Rows 7+14 item search · 8 customer display · 10 new-customer button · 11
Quotation → Sales Invoice / Delivery Note · 12 Sales Order as Delivery Note ·
16 auto-translate off · 24 prepayment block · 27 list filters.

Runs on `yht-test`, where `yht_features` is `["all"]`, so every switch is on;
the one test that needs a switch OFF monkeypatches `features.enabled`.
"""

import json
import pathlib
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import features, field_layout, form_layout, link_sort, print_heading
from yht_custom.item_search import FEATURE as ITEM_SEARCH_FEATURE
from yht_custom.item_search import item_query, search_words
from yht_custom.quotation_flow import _customer_of, make_delivery_note

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _source(relative: str) -> str:
	return (ROOT / relative).read_text()


# ------------------------------------------------------------------ switches


class TestTheSwitchesAreRegistered(FrappeTestCase):
	"""A switch name that is not in KNOWN raises; one the JS spells differently
	silently reads as off forever. Both are caught here."""

	NAMES = (
		"oct08_r07_item_search",
		"oct08_r10_new_customer_button",
		"oct08_r11_quotation_create",
		"oct08_r12_so_delivery_note",
		"oct08_r23_invoice_first_dn_link",
		"oct08_r24_prepayment_block",
		"oct08_r27_list_filters",
	)

	def test_every_switch_is_known(self):
		for name in self.NAMES:
			with self.subTest(switch=name):
				self.assertIn(name, features.KNOWN)
				features.enabled(name)  # must not raise

	def test_the_client_scripts_spell_their_switch_exactly(self):
		pairs = (
			("public/js/create_customer.js", "oct08_r10_new_customer_button"),
			("public/js/quotation_create.js", "oct08_r11_quotation_create"),
			("public/js/item_search.js", "oct08_r07_item_search"),
		)
		for path, name in pairs:
			with self.subTest(file=path):
				self.assertIn(f'"{name}"', _source(path))

	def test_the_router_and_template_spell_the_print_switch_exactly(self):
		import json

		shim = json.loads(_source("yht_custom/print_format/katc_sales_order/katc_sales_order.json"))
		self.assertIn('yht_feature("oct08_r12_so_delivery_note")', shim["html"])
		self.assertIn("katc_as_delivery", _source("templates/includes/katc/sales_order.html"))


# ------------------------------------------------------------ rows 7 and 14


class TestTheClientRewritesThePickerQuery(FrappeTestCase):
	"""`item_search.js` is the lever that actually reaches the picker (gotcha 118)."""

	def test_the_script_is_included_and_names_both_methods(self):
		src = _source("public/js/item_search.js")
		for needle in (
			'"erpnext.controllers.queries.item_query"',
			'"yht_custom.item_search.item_query"',
			"set_custom_query",
			f'"{ITEM_SEARCH_FEATURE}"',
		):
			with self.subTest(needle=needle):
				self.assertIn(needle, src)

		from yht_custom import hooks

		self.assertTrue(
			any(path.startswith("/assets/yht_custom/js/item_search.js?v=") for path in hooks.app_include_js),
			"item_search.js is not in app_include_js",
		)

	def test_the_hook_stays_for_direct_api_calls(self):
		from yht_custom import hooks

		self.assertEqual(
			hooks.override_whitelisted_methods["erpnext.controllers.queries.item_query"],
			"yht_custom.item_search.item_query",
		)

	def test_frappe_still_builds_the_request_through_set_custom_query(self):
		"""The hook point is frappe's, not ours. If an upgrade renames it the
		rewrite stops silently and every picker is upstream again."""
		link_js = pathlib.Path(
			frappe.get_app_path("frappe", "public", "js", "frappe", "form", "controls", "link.js")
		).read_text()
		self.assertIn("set_custom_query(args) {", link_js)
		self.assertLess(
			link_js.index("me.set_custom_query(args)"),
			link_js.index('method: "frappe.desk.search.search_link"'),
			"set_custom_query no longer runs before the search_link call",
		)


class TestItemSearch(FrappeTestCase):
	"""Rows 7 + 14 — every word must match, and the order is the item code."""

	def setUp(self):
		group = frappe.get_all("Item Group", filters={"is_group": 0}, pluck="name", limit=1)[0]
		uom = frappe.get_all("UOM", pluck="name", limit=1)[0]
		self.codes = []
		for code, name, description in (
			("_T-R07-ELBOW-025", "ZQXTEST ELBOW 90 DEG 1 INCH SS", "Stainless steel elbow, ninety degrees, one inch"),
			("_T-R07-ELBOW-008", "ZQXTEST ELBOW 90 DEG 1/4 INCH SS", "Stainless steel elbow, ninety degrees, quarter inch"),
			("_T-R07-TEE-025", "ZQXTEST TEE EQUAL 1 INCH SS", "Stainless steel equal tee, one inch"),
		):
			# `FrappeTestCase` rolls back once per CLASS (gotcha 50), so a fixture
			# inserted in `setUp` is still there for the next test method.
			if not frappe.db.exists("Item", code):
				frappe.get_doc(
					{
						"doctype": "Item",
						"item_code": code,
						"item_name": name,
						"description": description,
						"item_group": group,
						"stock_uom": uom,
						"is_stock_item": 0,
					}
				).insert(ignore_permissions=True)
			self.codes.append(code)

	def _names(self, txt, filters=None):
		return [row[0] for row in item_query("Item", txt, None, 0, 50, filters or {})]

	def test_every_word_must_match_in_any_order(self):
		"""ZQXTEST is the fixture's own token: 4,000 real items also contain
		"elbow", "ss" and "1", and a page of 50 would never reach `_T-…`."""
		found = [n for n in self._names("zqxtest elbow ss 1 inch") if n.startswith("_T-R07")]
		self.assertEqual(found, ["_T-R07-ELBOW-008", "_T-R07-ELBOW-025"])
		# Same words, different order — same answer.
		self.assertEqual([n for n in self._names("1 inch ss elbow zqxtest") if n.startswith("_T-R07")], found)
		# A word that matches nothing on the row excludes it, however many others hit.
		# (Not "tee": the match is a substring, and "sTEEl" is in every description.)
		self.assertEqual([n for n in self._names("zqxtest elbow ss valve") if n.startswith("_T-R07")], [])

	def _search_link(self, query, txt):
		"""The desk's own path — `link.js` → `search_link` → `search_widget` →
		`frappe.call(query, …)`, with the kwargs 15.118 adds on top of upstream's
		positional contract."""
		from frappe.desk.search import search_link

		rows = search_link(
			"Item",
			txt,
			query=query,
			filters=json.dumps({"has_variants": 0}),
			page_length=50,
			reference_doctype="Sales Invoice Item",
			ignore_user_permissions=False,
		)
		return [r["value"] for r in rows if r["value"].startswith("_T-R07")]

	def test_the_picker_reaches_the_query_through_search_link(self):
		found = self._search_link("yht_custom.item_search.item_query", "zqxtest elbow ss 1 inch")
		self.assertEqual(found, ["_T-R07-ELBOW-008", "_T-R07-ELBOW-025"])

	def test_search_link_does_not_honour_the_server_override(self):
		"""Why `public/js/item_search.js` exists. `hooks.override_whitelisted_methods`
		maps upstream's name to ours, and the picker's path ignores it — upstream's
		whole-string LIKE finds no fixture. If this ever FAILS, frappe has started
		honouring the hook in `desk/search.py` and the client rewrite can go."""
		found = self._search_link("erpnext.controllers.queries.item_query", "zqxtest elbow ss 1 inch")
		self.assertEqual(found, [])

	def test_a_word_may_live_in_the_description_only(self):
		found = [n for n in self._names("zqxtest ninety quarter") if n.startswith("_T-R07")]
		self.assertEqual(found, ["_T-R07-ELBOW-008"])

	def test_the_order_is_the_item_code_not_idx(self):
		"""Row 7's root cause. idx is set so that upstream's `idx desc` would reverse them."""
		frappe.db.set_value("Item", "_T-R07-ELBOW-008", "idx", 1, update_modified=False)
		frappe.db.set_value("Item", "_T-R07-ELBOW-025", "idx", 999, update_modified=False)
		found = [n for n in self._names("zqxtest elbow") if n.startswith("_T-R07")]
		self.assertEqual(found, ["_T-R07-ELBOW-008", "_T-R07-ELBOW-025"])

	def test_a_code_prefix_floats_that_code_to_the_top(self):
		names = self._names("_T-R07-TEE")
		self.assertTrue(names, "prefix search found nothing")
		self.assertEqual(names[0], "_T-R07-TEE-025")

	def test_filters_still_restrict(self):
		other = frappe.get_all("Item Group", filters={"is_group": 0}, pluck="name", limit=2)
		if len(other) < 2:
			self.skipTest("one item group only")
		wrong_group = [g for g in other if g != frappe.db.get_value("Item", "_T-R07-TEE-025", "item_group")][0]
		self.assertEqual([n for n in self._names("zqxtest tee", {"item_group": wrong_group}) if n.startswith("_T-R07")], [])

	def test_switch_off_is_upstream_byte_for_byte(self):
		from erpnext.controllers.queries import item_query as upstream

		original = features.enabled
		try:
			features.enabled = lambda name: False if name == ITEM_SEARCH_FEATURE else original(name)
			ours = item_query("Item", "_T-R07", None, 0, 20, {})
		finally:
			features.enabled = original
		self.assertEqual(list(ours), list(upstream("Item", "_T-R07", None, 0, 20, {})))

	def test_search_words_caps_and_cleans(self):
		self.assertEqual(search_words("  elbow   90 "), ["elbow", "90"])
		self.assertEqual(len(search_words(" ".join(str(i) for i in range(20)))), 8)
		self.assertEqual(search_words(None), [])


# ---------------------------------------------------------------------- row 8


class TestCustomerPickerShowsTheName(FrappeTestCase):
	def test_customer_is_listed_and_title_field_is_a_real_field(self):
		self.assertIn("Customer", link_sort.LINK_TITLE_DISPLAY)
		meta = frappe.get_meta("Customer")
		self.assertTrue(meta.get_field(meta.title_field))

	def test_the_step_sets_the_doctype_property(self):
		applied = link_sort.setup_link_title_display()
		self.assertEqual(applied.get("Customer"), "customer_name")
		frappe.clear_cache(doctype="Customer")
		self.assertEqual(int(frappe.get_meta("Customer").show_title_field_in_link or 0), 1)
		row = frappe.db.get_value(
			"Property Setter",
			{"doc_type": "Customer", "property": "show_title_field_in_link"},
			["doctype_or_field", "value"],
			as_dict=True,
		)
		self.assertEqual((row.doctype_or_field, row.value), ("DocType", "1"))


# --------------------------------------------------------------------- row 10


class TestNewCustomerButtonOnlyBeforeSave(FrappeTestCase):
	def test_the_script_removes_the_button_once_saved(self):
		src = _source("public/js/create_customer.js")
		self.assertIn("!frm.is_new()", src)
		self.assertIn("$existing.remove()", src)
		# The pre-row-10 rule survives for a site with the switch off.
		self.assertIn("frm.doc.docstatus !== 0", src)


# --------------------------------------------------------------------- row 11


class TestQuotationCreateButtons(FrappeTestCase):
	def test_both_buttons_name_their_server_method(self):
		src = _source("public/js/quotation_create.js")
		self.assertIn("erpnext.selling.doctype.quotation.quotation.make_sales_invoice", src)
		self.assertIn("yht_custom.quotation_flow.make_delivery_note", src)
		self.assertIn('frm.doc.docstatus !== 1', src)

	def test_the_upstream_invoice_mapper_exists_on_this_bench(self):
		self.assertTrue(frappe.get_attr("erpnext.selling.doctype.quotation.quotation.make_sales_invoice"))

	def test_the_delivery_note_mapper_is_whitelisted(self):
		self.assertIn(frappe.get_attr("yht_custom.quotation_flow.make_delivery_note"), frappe.whitelisted)

	def test_the_quotation_is_registered_for_the_script(self):
		from yht_custom import hooks

		self.assertIn("public/js/quotation_create.js", hooks.doctype_js["Quotation"])

	def _submitted_customer_quotation(self):
		rows = frappe.get_all(
			"Quotation",
			filters={"docstatus": 1, "quotation_to": "Customer"},
			fields=["name", "party_name"],
			order_by="modified desc",
			limit=5,
		)
		for row in rows:
			if frappe.db.count("Quotation Item", {"parent": row.name, "is_alternative": 0}):
				return row
		self.skipTest("no submitted Quotation to a Customer on this site")

	def test_a_delivery_note_is_mapped_from_a_submitted_quotation(self):
		row = self._submitted_customer_quotation()
		dn = make_delivery_note(row.name)
		self.assertEqual(dn.doctype, "Delivery Note")
		self.assertEqual(dn.customer, row.party_name)
		source = frappe.get_all(
			"Quotation Item",
			filters={"parent": row.name, "is_alternative": 0},
			fields=["item_code", "qty", "rate"],
			order_by="idx",
		)
		self.assertEqual([d.item_code for d in dn.items], [s.item_code for s in source])
		self.assertEqual([(d.qty, d.rate) for d in dn.items], [(s.qty, s.rate) for s in source])
		# No order behind this note, and the row says so.
		self.assertFalse(any(d.against_sales_order for d in dn.items))

	def test_a_lead_quotation_is_refused_with_the_reason(self):
		name = frappe.db.get_value("Quotation", {"docstatus": 1, "quotation_to": "Lead"}, "name")
		if not name:
			self.skipTest("no submitted Quotation to a Lead on this site")
		with self.assertRaises(frappe.ValidationError):
			_customer_of(name)


# --------------------------------------------------------------------- row 12


class TestSalesOrderPrintsAsDeliveryNote(FrappeTestCase):
	"""Nothing here writes to the database: `frappe.get_print` commits (gotcha 84)."""

	def test_the_option_and_its_heading_exist(self):
		self.assertIn("Delivery Note", print_heading.PRINT_AS["Sales Order"])
		self.assertIn("Delivery Note", print_heading.ARABIC)
		self.assertTrue(frappe.db.exists("Print Heading", "Delivery Note"))

	def _submitted_sales_order(self):
		name = frappe.db.get_value("Sales Order", {"docstatus": 1}, "name", order_by="modified desc")
		if not name:
			self.skipTest("no submitted Sales Order on this site")
		return frappe.get_doc("Sales Order", name)

	def test_delivery_mode_drops_money_and_says_delivery_note(self):
		if not features.enabled("oct08_r12_so_delivery_note"):
			self.skipTest("switch off on this site")
		doc = self._submitted_sales_order()
		doc.custom_print_as = "Delivery Note"
		html = frappe.get_print("Sales Order", doc.name, "KATC Sales Order", doc=doc)
		self.assertIn("DELIVERY NOTE", html)
		self.assertNotIn("Grand Total", html)
		self.assertNotIn(">Rate<", html)
		self.assertNotIn("In Words", html)
		self.assertIn("Quantity", html)

	def test_the_ordinary_sales_order_still_carries_its_totals(self):
		doc = self._submitted_sales_order()
		doc.custom_print_as = "Sales Order"
		html = frappe.get_print("Sales Order", doc.name, "KATC Sales Order", doc=doc)
		self.assertIn("Grand Total", html)
		self.assertIn(">Rate<", html)
		self.assertNotIn("DELIVERY NOTE", html)

	# -- every path the client can print through, not only the router --------

	def _shim(self, folder):
		import json

		return json.loads(_source(f"yht_custom/print_format/{folder}/{folder}.json"))["html"]

	def _render_with(self, html, doc):
		"""Render a shipped router/shim as the desk would, from an in-memory Print
		Format: the Arabic, No LH and Proforma records are disabled on this site by
		CR-004, and `frappe.get_print` refuses a disabled record (and commits)."""
		from frappe.www.printview import get_rendered_template

		print_format = frappe.get_doc(
			{
				"doctype": "Print Format",
				"name": "_T-R12-shim",
				"doc_type": "Sales Order",
				"module": "Yht Custom",
				"print_format_type": "Jinja",
				"custom_format": 1,
				"standard": "No",
				"html": html,
			}
		)
		return get_rendered_template(doc, print_format=print_format, no_letterhead=1)

	def test_every_sales_order_format_honours_print_as_delivery_note(self):
		"""Osaid, 2026-10-10: "the option is showing but when printing sales order as
		a delivery note … the format is still showing sales order". The decision lived
		in the KATC Sales Order router only; the Arabic and No LH shims (enabled on the
		live site) and the Proforma router — the live site's DEFAULT for Sales Order —
		never set it."""
		if not features.enabled("oct08_r12_so_delivery_note"):
			self.skipTest("switch off on this site")
		doc = self._submitted_sales_order()
		doc.custom_print_as = "Delivery Note"
		for folder in ("katc_sales_order", "katc_sales_order_arabic", "katc_sales_order_no_lh", "katc_proforma_invoice"):
			with self.subTest(format=folder):
				html = self._render_with(self._shim(folder), doc)
				self.assertIn("DELIVERY NOTE", html)
				self.assertNotIn(">Rate<", html)
				self.assertNotIn("Grand Total", html)

	def test_the_live_conditions_heading_switch_off_and_the_old_shims(self):
		"""Production: `cr_004_print_heading` is OFF, and the `KATC Sales Order` /
		`KATC Proforma Invoice` records are the OLD plain `{% include %}`s until a
		migrate replaces them — so the layout has to come from the shared template and
		the title from the legacy path. UAT has every switch on and the new routers, so
		this is the only place that conditions are exercised. Row 12 shipped to live
		on 2026-10-11 on the strength of it."""
		if not features.enabled("oct08_r12_so_delivery_note"):
			self.skipTest("switch off on this site")
		doc = self._submitted_sales_order()
		real = features.enabled
		old_shims = {
			"old KATC Sales Order": '{% include "yht_custom/templates/includes/katc/sales_order.html" %}',
			"old KATC Sales Order Arabic": '{% set katc_show_arabic = true %}{% include "yht_custom/templates/includes/katc/sales_order.html" %}',
			"new Proforma router": self._shim("katc_proforma_invoice"),
		}
		with mock.patch.object(features, "enabled", side_effect=lambda n: False if n == "cr_004_print_heading" else real(n)):
			for label, html in old_shims.items():
				with self.subTest(shim=label):
					doc.custom_print_as = "Delivery Note"
					out = self._render_with(html, doc)
					self.assertIn("DELIVERY NOTE", out)
					self.assertNotIn(">Rate<", out)
					self.assertNotIn("Grand Total", out)
			doc.custom_print_as = "Sales Order"
			self.assertIn("PROFORMA INVOICE", self._render_with(old_shims["new Proforma router"], doc))

	def test_the_proforma_router_still_prints_a_proforma_otherwise(self):
		doc = self._submitted_sales_order()
		doc.custom_print_as = "Sales Order"
		html = self._render_with(self._shim("katc_proforma_invoice"), doc)
		self.assertIn("PROFORMA INVOICE", html)
		self.assertNotIn("DELIVERY NOTE", html)

	def test_print_as_quotation_titles_the_page_quotation(self):
		"""Measured 2026-10-10 through the printer icon: Print As = Quotation printed
		SALES ORDER, because `select_print_heading` (auto-filled on every order) came
		first in the title resolution. On a Sales Order, Print As is the control."""
		if not features.enabled("cr_004_print_heading"):
			self.skipTest("switch off on this site")
		doc = self._submitted_sales_order()
		doc.custom_print_as = "Quotation"
		doc.select_print_heading = "Sales Order"
		html = frappe.get_print("Sales Order", doc.name, "KATC Sales Order", doc=doc)
		self.assertIn(">QUOTATION<", html)
		self.assertNotIn("SALES ORDER", html)

	def test_the_printer_icon_reaches_the_router(self):
		"""The icon prints `meta.default_print_format`. `YHT Sales Order` is a builder
		format that cannot read Print As — that is the path Osaid printed through."""
		from yht_custom import setup

		self.assertEqual(setup.DEFAULT_PRINT_FORMATS["Sales Order"], "KATC Sales Order")
		setup.setup_default_print_formats()
		frappe.clear_cache(doctype="Sales Order")
		self.assertEqual(frappe.get_meta("Sales Order").default_print_format, "KATC Sales Order")


# --------------------------------------------------------------------- row 16


class TestAutoTranslateIsOff(FrappeTestCase):
	def test_the_setting_is_on_where_the_app_carries_it(self):
		if not frappe.db.exists("DocType", "Arabic Translation Key"):
			self.skipTest("arabic_translation not installed")
		if not frappe.get_meta("Arabic Translation Key").has_field("disable_auto_translate"):
			self.skipTest("arabic_translation on this bench predates the switch")
		from yht_custom.site_defaults import _disable_arabic_auto_translate

		_disable_arabic_auto_translate()
		self.assertEqual(int(frappe.db.get_single_value("Arabic Translation Key", "disable_auto_translate")), 1)


# --------------------------------------------------------------------- row 23


class TestInvoiceFirstDeliveryNoteCarriesTheInvoiceNumber(FrappeTestCase):
	"""Row 23 — reproduced on UAT 2026-10-10: against_sales_invoice on every row,
	the invoice naming the note, and `custom_sales_invoice_no` still empty."""

	def test_a_note_mapped_from_an_invoice_names_it_at_validate(self):
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_delivery_note

		from yht_custom.dn_links import set_order_numbers

		name = frappe.db.sql(
			"""select si.name from `tabSales Invoice` si
			   where si.docstatus = 1 and si.is_return = 0 and ifnull(si.update_stock, 0) = 0
			     and not exists (select 1 from `tabSales Invoice Item` i
			                     where i.parent = si.name and ifnull(i.delivery_note, '') != '')
			   order by si.modified desc limit 1""",
			pluck="name",
		)
		if not name:
			self.skipTest("no invoice-first candidate on this site")
		dn = make_delivery_note(name[0])
		self.assertTrue(dn.items and all(r.against_sales_invoice == name[0] for r in dn.items))
		set_order_numbers(dn)
		self.assertEqual(dn.custom_sales_invoice_no, name[0])

	def test_a_resave_keeps_what_the_invoice_side_wrote(self):
		from yht_custom.dn_links import set_order_numbers

		dn = frappe.new_doc("Delivery Note")
		dn.custom_sales_invoice_no = "KSIN-00-0001"
		dn.append("items", {"item_code": "x", "qty": 1, "against_sales_invoice": "KSIN-00-0002"})
		set_order_numbers(dn)
		self.assertEqual(dn.custom_sales_invoice_no, "KSIN-00-0001, KSIN-00-0002")

	def test_the_fill_waits_for_its_switch(self):
		"""Osaid, 2026-10-10: row 23 stays off the live site until discussed. The
		FIELD arrives with the migrate; the fill is switched separately."""
		from unittest import mock

		from yht_custom import dn_links

		dn = frappe.new_doc("Delivery Note")
		dn.append("items", {"item_code": "x", "qty": 1, "against_sales_invoice": "KSIN-00-0002"})
		with mock.patch.object(
			dn_links.features, "enabled", side_effect=lambda name: name != dn_links.INVOICE_FIRST_FEATURE
		):
			dn_links.set_order_numbers(dn)
		self.assertFalse(dn.custom_sales_invoice_no)


# --------------------------------------------------------------------- row 24


class TestPrepaymentBlock(FrappeTestCase):
	def test_payment_entry_is_ordered_by_one_mechanism_only(self):
		self.assertIn("Payment Entry", field_layout.FIELD_ORDER)
		self.assertNotIn("Payment Entry", field_layout.FIELD_MOVES)

	def test_the_block_is_collapsible_labelled_and_under_the_tick(self):
		form_layout.setup_prepayment_block()
		field_layout.apply_field_moves()
		frappe.clear_cache(doctype="Payment Entry")
		meta = frappe.get_meta("Payment Entry")
		for fieldname in form_layout.PE_PREPAYMENT_SECTION_LABELS:
			with self.subTest(section=fieldname):
				self.assertEqual(int(meta.get_field(fieldname).collapsible or 0), 1)
		self.assertEqual(meta.get_field("section_break_56").label, "Prepayment Tax Lines")
		self.assertEqual(meta.get_field("section_break_60").label, "Prepayment Tax Totals")
		order = [f.fieldname for f in meta.fields]
		self.assertLess(order.index("taxes_and_charges_section"), order.index("party_section"))
		self.assertLess(order.index("custom_prepayment_invoice"), order.index("taxes_and_charges_section"))
		# Everything else is still there — a declared prefix drops nothing.
		self.assertIn("deductions_or_loss_section", order)
		self.assertIn("subscription_section", order)

	def test_both_halves_of_row_24_wait_for_one_switch(self):
		"""Osaid, 2026-10-10: rows 20, 23, 24 and 27 stay off the live site until
		discussed. A migrate for rows 7–17 must therefore leave these setters alone."""
		from unittest import mock

		off = {"oct08_r24_prepayment_block", "oct08_r27_list_filters"}
		with mock.patch.object(features, "enabled", side_effect=lambda name: name not in off):
			self.assertIn("skipped", form_layout.setup_prepayment_block())
			self.assertIn("skipped", form_layout.setup_list_filters())
			skipped = []
			field_layout._apply_field_order(skipped)
		self.assertEqual(field_layout.FIELD_ORDER_SWITCHES.get("Payment Entry"), "oct08_r24_prepayment_block")
		self.assertTrue(any(s.startswith("Payment Entry: oct08_r24_prepayment_block") for s in skipped), skipped)


# --------------------------------------------------------------------- row 27


class TestListFilters(FrappeTestCase):
	def test_the_expense_flag_joins_the_filter_row(self):
		form_layout.setup_list_filters()
		frappe.clear_cache(doctype="Purchase Invoice")
		self.assertEqual(
			int(frappe.get_meta("Purchase Invoice").get_field("custom_is_expense_invoice").in_standard_filter or 0), 1
		)

	def test_the_rest_of_row_27_was_already_there(self):
		"""Measured before building: is_return on four lists, payment_type upstream."""
		self.assertEqual(int(frappe.get_meta("Payment Entry").get_field("payment_type").in_standard_filter or 0), 1)
		for doctype in form_layout.RETURN_SPLIT_LISTS:
			with self.subTest(doctype=doctype):
				self.assertEqual(int(frappe.get_meta(doctype).get_field("is_return").in_standard_filter or 0), 1)
