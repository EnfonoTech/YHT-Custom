# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Meeting of 2026-10-11 — the Wednesday batch (sheet rows 13, 26, 30, 32, 33, 35).

TDD, written BEFORE the implementation (spec: `.pipeline/spec.md`). Every test here is
expected to be RED until the matching step is built; the ones marked CHARACTERISATION in
the docstring pin today's behaviour that the batch must not disturb and are green already.

Runs on `yht-test` only (`yht_features` is `["all"]` there):

    bench --site yht-test run-tests --app yht_custom --skip-before-tests \
        --module yht_custom.tests.test_meeting_1011_wednesday

House rules (CLAUDE.md): nothing commits (gotcha 74) — the one function that does,
`print_consolidation.restore`, is run with `frappe.db.commit` patched out; nothing renders
through `frappe.get_print` (gotcha 84) — prints go through
`printview.get_rendered_template(doc=…)`; the desk's real path is used for the search
(gotcha 118); FrappeTestCase rolls back per CLASS (gotcha 50/114), so fixtures are built
idempotently and anything a test sets outside the DB transaction (user defaults, the
user-settings cache) is restored in a `finally`.

New modules are imported lazily through `_mod()` so each test fails on its own with an
ImportError rather than the whole module failing to collect.

CONVENTION THE IMPLEMENTER MUST FOLLOW (stated in the spec only loosely): the row-30 print
additions are bracketed by PAIRS of `{# r30 #}` comment lines — one on the line before the
gated block, one on the line after — so the test can strip exactly the gated lines and
byte-compare the switch-OFF output against that stripped template.
"""

import ast
import contextlib
import hashlib
import importlib
import json
import pathlib
import re
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint, flt, getdate

from yht_custom import features
from yht_custom.tests.test_client_print_defaults import _clear, _format, _one_of_ours, _setter

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRANCH_USER = "branchtest@yht-khobhar.enfonoerp.com"

R13 = "oct11_r13_sales_history"
R26 = "oct11_r26_session_fiscal_year"
R30 = "oct11_r30_front_details"
R32 = "oct11_r32_doc_number_search"
R33 = "oct11_r33_record_expense"

SWITCHES = (R13, R26, R30, R32, R33)
SELLING = ("Quotation", "Sales Order", "Sales Invoice", "Delivery Note")
ITEM_DOCTYPES = ("Quotation Item", "Sales Order Item", "Sales Invoice Item", "Delivery Note Item")
SENTINEL_VALUATION = 987654.321


# ------------------------------------------------------------------ helpers


def _mod(dotted: str):
	return importlib.import_module(dotted)


def _wed():
	return _mod("yht_custom.meeting_1011_wednesday")


def _sy():
	return _mod("yht_custom.session_year")


def _dns():
	return _mod("yht_custom.doc_number_search")


def _source(relative: str) -> str:
	return (ROOT / relative).read_text()


def _off(*names):
	"""`features.enabled` with the named switches forced off, the rest as configured."""
	real = features.enabled
	return mock.patch.object(
		features, "enabled", side_effect=lambda n: False if n in names else real(n)
	)


def _fieldnames(doctype):
	return [f.fieldname for f in frappe.get_meta(doctype).fields]


def _cache():
	return frappe.cache() if callable(frappe.cache) else frappe.cache


def _sold_row():
	"""(item_code, warehouse) of a submitted, non-return sales line that names a warehouse."""
	rows = frappe.db.sql(
		"""SELECT sii.item_code, sii.warehouse FROM `tabSales Invoice Item` sii
		INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE si.docstatus = 1 AND si.is_return = 0 AND IFNULL(sii.warehouse, '') != ''
		LIMIT 1""",
		as_dict=True,
	)
	return (rows[0].item_code, rows[0].warehouse) if rows else (None, None)


def _a_doc(doctype, **filters):
	name = frappe.db.get_value(doctype, {"docstatus": 1, **filters}, "name", order_by="modified desc")
	if not name:
		return None
	return frappe.get_doc(doctype, name)


def _rowkey(row, *candidates):
	for key in candidates:
		if key in row:
			return row[key]
	return None


@contextlib.contextmanager
def _as_user(user):
	frappe.clear_cache(user=user)
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user("Administrator")


# ------------------------------------------------------------ print helpers

_INCLUDE = re.compile(r'\{%-?\s*include\s+"([^"]+)"\s*-?%\}')


def _format_html(name: str) -> str:
	return json.loads(_source(f"yht_custom/print_format/{name}/{name}.json"))["html"]


def _inline(html: str) -> str:
	"""Replace each `{% include "yht_custom/templates/…" %}` with the file's own text, so
	the switch-off render can be compared against a version with the r30 lines stripped."""

	def sub(match):
		path = match.group(1)
		prefix = "yht_custom/"
		return _source(path[len(prefix):]) if path.startswith(prefix) else match.group(0)

	return _INCLUDE.sub(sub, html)


def _strip_r30(html: str) -> str:
	"""Remove every line from one `{# r30 #}` marker to the next (inclusive), in pairs."""
	lines, out, inside = html.split("\n"), [], False
	for line in lines:
		if "{# r30 #}" in line:
			inside = not inside
			continue
		if not inside:
			out.append(line)
	assert not inside, "unpaired {# r30 #} marker"
	return "\n".join(out)


def _render(doc, html, print_format_doctype=None):
	from frappe.www.printview import get_rendered_template

	print_format = frappe.get_doc(
		{
			"doctype": "Print Format",
			"name": "_T-WED-shim",
			"doc_type": print_format_doctype or doc.doctype,
			"module": "Yht Custom",
			"print_format_type": "Jinja",
			"custom_format": 1,
			"standard": "No",
			"html": html,
		}
	)
	return get_rendered_template(doc, print_format=print_format, no_letterhead=1)


# ===================================================================== switches


class TestTheSwitchesAreRegistered(FrappeTestCase):
	def test_every_switch_is_known(self):
		for name in SWITCHES:
			with self.subTest(switch=name):
				self.assertIn(name, features.KNOWN)
				features.enabled(name)  # must not raise

	def test_the_scripts_spell_their_switch_exactly(self):
		pairs = (
			("public/js/price_assist.js", R13),
			("public/js/session_year.js", R26),
			("public/js/expense_invoice.js", R33),
			("yht_custom/page/yht_dashboard/yht_dashboard.js", R33),
		)
		for path, name in pairs:
			with self.subTest(file=path):
				self.assertIn(f'"{name}"', _source(path))

	def test_the_python_modules_spell_their_switch_exactly(self):
		for module, switch in (
			("yht_custom.meeting_1011_wednesday", R30),
			("yht_custom.meeting_1011_wednesday", R13),
			("yht_custom.session_year", R26),
			("yht_custom.doc_number_search", R32),
			("yht_custom.expense_invoice", R33),
		):
			with self.subTest(module=module, switch=switch):
				self.assertIn(f'"{switch}"', pathlib.Path(_mod(module).__file__).read_text())

	def test_hooks_carry_the_cache_busters_the_override_and_no_fixtures_for_new_fields(self):
		hooks = _source("hooks.py")
		self.assertIn("price_assist.js?v=9", hooks)
		self.assertIn("expense_invoice.js?v=6", hooks)
		self.assertIn("session_year.js?v=2", hooks)
		self.assertNotIn("price_assist.js?v=8", hooks)
		self.assertNotIn("expense_invoice.js?v=5", hooks)
		override = frappe.get_hooks("override_whitelisted_methods", app_name="yht_custom") or {}
		self.assertIn("frappe.utils.global_search.search", override)
		self.assertIn(
			"yht_custom.doc_number_search.search", str(override["frappe.utils.global_search.search"])
		)
		fixtures = str(frappe.get_hooks("fixtures", app_name="yht_custom"))
		for name in ("custom_valuation_rate", "custom_front_party", "custom_front_team"):
			self.assertNotIn(name, fixtures)  # a fixture reaches live on its next migrate (D14)

	def test_four_provisioning_steps_are_registered_in_order_and_resolvable(self):
		from yht_custom import setup

		steps = list(setup.PROVISIONING_STEPS)
		new = ("setup_valuation_column", "setup_front_details", "setup_session_year", "setup_record_expense")
		for name in new:
			with self.subTest(step=name):
				self.assertIn(name, steps)
				self.assertTrue(callable(setup._imported(name)))
		self.assertGreater(steps.index("setup_front_details"), steps.index("setup_heading_front"))
		self.assertGreater(steps.index("setup_front_details"), steps.index("setup_print_with_arabic"))
		self.assertGreater(steps.index("setup_valuation_column"), steps.index("setup_branch_purchase_order"))


# ======================================================================= row 13


class TestRow13ValuationColumn(FrappeTestCase):
	def setUp(self):
		_wed().setup_valuation_column()

	def test_the_field_exists_on_all_four_item_doctypes_and_is_screen_only(self):
		for doctype in ITEM_DOCTYPES:
			with self.subTest(doctype=doctype):
				field = frappe.get_meta(doctype).get_field("custom_valuation_rate")
				self.assertIsNotNone(field)
				self.assertEqual(field.fieldtype, "Currency")
				self.assertEqual(cint(field.print_hide), 1)
				self.assertEqual(cint(field.read_only), 1)
				self.assertEqual(cint(field.in_list_view), 1)
				self.assertEqual(cint(field.allow_on_submit), 0)
				self.assertEqual(cint(field.no_copy), 0)  # a mapped Delivery Note keeps the number

	def test_it_sits_directly_after_rate_even_where_a_field_order_setter_exists(self):
		for doctype in ITEM_DOCTYPES:
			with self.subTest(doctype=doctype):
				order = _fieldnames(doctype)
				self.assertEqual(order.index("custom_valuation_rate"), order.index("rate") + 1)

	def test_the_standard_valuation_rate_fields_are_left_alone(self):
		for doctype in ("Quotation Item", "Sales Order Item"):
			with self.subTest(doctype=doctype):
				field = frappe.get_meta(doctype).get_field("valuation_rate")
				self.assertEqual(cint(field.print_hide), 1)
				self.assertEqual(cint(field.in_list_view), 0)

	def test_the_grid_budget_holds_and_the_columns_are_exactly_these(self):
		"""Gotcha 52 as an assertion: grid.js starts at 1 and drops every column after >11.

		No last-column check: Quotation Item's last column is `amount` (actual_qty is earlier in field order)."""
		expected = {
			"item_code": 2, "qty": 1, "uom": 1, "discount_percentage": 1,
			"rate": 2, "custom_valuation_rate": 1, "amount": 1, "actual_qty": 1,
		}
		for doctype in ITEM_DOCTYPES:
			with self.subTest(doctype=doctype):
				grid = [f for f in frappe.get_meta(doctype).fields if cint(f.in_list_view) and not cint(f.hidden)]
				total = 1 + sum(cint(f.columns) for f in grid)
				self.assertLessEqual(total, 11)
				self.assertEqual({f.fieldname: cint(f.columns) for f in grid}, expected)

	def test_sales_order_delivery_date_leaves_the_grid(self):
		self.assertEqual(cint(frappe.get_meta("Sales Order Item").get_field("delivery_date").in_list_view), 0)

	def test_the_step_is_idempotent(self):
		before = {d: _fieldnames(d) for d in ITEM_DOCTYPES}
		_wed().setup_valuation_column()
		for doctype in ITEM_DOCTYPES:
			with self.subTest(doctype=doctype):
				self.assertEqual(
					frappe.db.count("Custom Field", {"dt": doctype, "fieldname": "custom_valuation_rate"}), 1
				)
				self.assertEqual(before[doctype], _fieldnames(doctype))

	def test_off_writes_nothing(self):
		with _off(R13), mock.patch(
			"frappe.custom.doctype.custom_field.custom_field.create_custom_fields"
		) as create:
			result = _wed().setup_valuation_column()
		self.assertIn("skipped", result)
		create.assert_not_called()


class TestRow13ServerEndpoints(FrappeTestCase):
	def setUp(self):
		self.item, self.warehouse = _sold_row()
		if not self.item:
			self.skipTest("no submitted sales history on this site")
		self.pa = _mod("yht_custom.api.price_assist")

	def test_the_payload_has_the_four_blocks_in_the_order_the_popup_shows_them(self):
		out = self.pa.get_history_popup(self.item, limit=6)
		self.assertEqual(list(out)[:4], ["sales", "purchases", "stock", "assist"])
		for key in ("currency", "can_see_purchases"):
			self.assertIn(key, out)

	def test_sales_are_submitted_non_return_newest_first_and_capped(self):
		out = self.pa.get_history_popup(self.item, limit=3)
		self.assertLessEqual(len(out["sales"]), 3)
		dates = []
		for row in out["sales"]:
			for key in ("posting_date", "customer", "qty", "rate", "invoice"):
				self.assertIn(key, row)
			state = frappe.db.get_value("Sales Invoice", row["invoice"], ["docstatus", "is_return"])
			self.assertEqual(tuple(state), (1, 0))
			dates.append(getdate(row["posting_date"]))
		self.assertEqual(dates, sorted(dates, reverse=True))

	def test_purchases_union_receipts_without_double_counting(self):
		item = frappe.db.get_value("Purchase Invoice Item", {"docstatus": 1}, "item_code") or self.item
		out = self.pa.get_history_popup(item, limit=50)
		for row in out["purchases"]:
			self.assertIn(row["doc_type"], ("Purchase Invoice", "Purchase Receipt"))
			for key in ("posting_date", "supplier", "qty", "rate"):
				self.assertIn(key, row)
			if row["doc_type"] != "Purchase Receipt":
				continue
			name = _rowkey(row, "doc", "name", "docname", "receipt", "document")
			self.assertIsNotNone(name, "a purchase row must say which document it is")
			billed = frappe.db.sql(
				"""SELECT COUNT(*) FROM `tabPurchase Invoice Item` pii
				INNER JOIN `tabPurchase Receipt Item` pri ON pii.pr_detail = pri.name
				WHERE pri.parent = %s AND pri.item_code = %s AND pii.docstatus = 1""",
				(name, item),
			)[0][0]
			self.assertEqual(billed, 0, f"{name} is already billed, so it must not be listed")

	def _in_branch(self, doctype, name, item, warehouse):
		child = f"tab{doctype} Item"
		hits = frappe.db.sql(
			f"""SELECT COUNT(*) FROM `{child}` c INNER JOIN `tab{doctype}` p ON p.name = c.parent
			WHERE c.parent = %s AND c.item_code = %s
			AND (c.warehouse = %s OR (IFNULL(c.warehouse, '') = '' AND p.set_warehouse = %s))""",
			(name, item, warehouse, warehouse),
		)[0][0]
		return hits > 0

	def test_every_block_is_branch_scoped_and_admin_sees_a_superset(self):
		with mock.patch.object(self.pa, "_branch_warehouses", return_value=[self.warehouse]):
			scoped = self.pa.get_history_popup(self.item, limit=200)
		everyone = self.pa.get_history_popup(self.item, limit=200)
		self.assertTrue(scoped["sales"])
		for row in scoped["sales"]:
			self.assertTrue(self._in_branch("Sales Invoice", row["invoice"], self.item, self.warehouse))
		for row in scoped["purchases"]:
			doc = row["doc_type"]
			name = _rowkey(row, "doc", "name", "docname", "receipt", "invoice", "document")
			self.assertTrue(self._in_branch(doc, name, self.item, self.warehouse))
		for row in scoped["stock"]:
			self.assertEqual(row["warehouse"], self.warehouse)
		self.assertLessEqual({r["invoice"] for r in scoped["sales"]}, {r["invoice"] for r in everyone["sales"]})

	def test_sale_conditions_exclude_returns_only_when_asked(self):
		where, params = self.pa._sale_conditions(["WH-1"], None, exclude_returns=True)
		self.assertIn("si.is_return = 0", where)
		self.assertEqual(params["warehouses"], ["WH-1"])
		where, _params = self.pa._sale_conditions(["WH-1"], None)
		self.assertNotIn("si.is_return = 0", where)  # every existing caller stays byte-identical

	def test_a_role_without_purchase_invoice_read_gets_an_empty_block_not_an_error(self):
		asked = []
		original = frappe.has_permission

		def fake(doctype=None, *args, **kwargs):
			asked.append(doctype)
			if doctype == "Purchase Invoice":
				return False
			return original(doctype, *args, **kwargs)

		with mock.patch.object(frappe, "has_permission", side_effect=fake):
			out = self.pa.get_history_popup(self.item, limit=3)
		self.assertIn("Purchase Invoice", asked)
		self.assertEqual(out["purchases"], [])
		self.assertIs(out["can_see_purchases"], False)

	def test_the_popup_is_gated_on_sales_invoice_read(self):
		def fake(doctype=None, *args, **kwargs):
			if doctype == "Sales Invoice":
				frappe.throw("no", frappe.PermissionError)
			return True

		with mock.patch.object(frappe, "has_permission", side_effect=fake):
			with self.assertRaises(frappe.PermissionError):
				self.pa.get_history_popup(self.item)

	def test_an_item_code_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			self.pa.get_history_popup("")

	def test_the_assist_block_is_exactly_what_get_price_assist_returns(self):
		"""The refactor into a private `_assist` must leave `get_price_assist` byte-identical."""
		direct = self.pa.get_price_assist(self.item, qty=2)
		self.assertEqual(
			set(direct),
			{
				"item_code", "item_name", "stock_uom", "currency", "price_list", "restricted_to_warehouses",
				"price_list_rate", "last_to_this_customer", "last_to_anyone", "band", "stock",
				"valuation_rate", "qty",
			},
		)
		self.assertTrue(callable(getattr(self.pa, "_assist", None)))
		self.assertEqual(self.pa.get_history_popup(self.item, qty=2)["assist"], direct)

	def _bin_items(self, count):
		return frappe.get_all("Bin", filters={"actual_qty": [">", 0]}, pluck="item_code", limit=count * 4)[:count]

	def test_valuation_is_one_grouped_query_for_n_items(self):
		items = list(dict.fromkeys(self._bin_items(6)))
		if len(items) < 3:
			self.skipTest("not enough stocked items")
		real = frappe.db.sql
		with mock.patch.object(frappe.db, "sql", wraps=real) as spy:
			out = self.pa.get_valuation_rates(json.dumps(items))
		bin_queries = [c for c in spy.call_args_list if "tabBin" in str(c.args[0] if c.args else c.kwargs)]
		self.assertEqual(len(bin_queries), 1)
		self.assertEqual(set(out), set(items))

	def test_valuation_is_branch_scoped_and_unknown_items_are_none(self):
		real = frappe.db.sql
		with mock.patch.object(self.pa, "_branch_warehouses", return_value=[self.warehouse]):
			with mock.patch.object(frappe.db, "sql", wraps=real) as spy:
				out = self.pa.get_valuation_rates(json.dumps([self.item, "ZQXTEST-NO-SUCH-ITEM"]))
		self.assertIsNone(out["ZQXTEST-NO-SUCH-ITEM"])
		bin_sql = [str(c.args[0]) + str(c.args[1:]) for c in spy.call_args_list if "tabBin" in str(c.args[:1])]
		self.assertTrue(any(self.warehouse in text for text in bin_sql))

	def test_valuation_refuses_malformed_json_and_caps_the_list(self):
		with self.assertRaises((frappe.ValidationError, ValueError)):
			self.pa.get_valuation_rates("{not json")
		try:
			out = self.pa.get_valuation_rates(json.dumps([f"ZQXTEST-{i}" for i in range(201)]))
		except frappe.ValidationError:
			return  # refused outright is a valid way to cap
		self.assertLessEqual(len(out), 200)

	def test_valuation_needs_item_read(self):
		def fake(doctype=None, *args, **kwargs):
			if doctype == "Item":
				frappe.throw("no", frappe.PermissionError)
			return True

		with mock.patch.object(frappe, "has_permission", side_effect=fake):
			with self.assertRaises(frappe.PermissionError):
				self.pa.get_valuation_rates(json.dumps([self.item]))


class TestRow13NothingPrints(FrappeTestCase):
	"""Screen only: the sentinel in `custom_valuation_rate` must reach no customer-facing print."""

	def _assert_absent(self, output):
		self.assertNotIn("987654", output)
		self.assertNotIn("987,654", output)

	def test_the_valuation_never_prints_on_the_katc_formats(self):
		cases = (
			("Sales Invoice", "katc_tax_invoice"),
			("Delivery Note", "katc_delivery_note"),
			("Quotation", "katc_quotation"),
			("Sales Order", "katc_sales_order"),
			("Sales Order", "katc_proforma_invoice"),
		)
		for doctype, fmt in cases:
			with self.subTest(format=fmt):
				doc = _a_doc(doctype)
				if not doc:
					self.skipTest(f"no submitted {doctype}")
				for row in doc.get("items"):
					row.custom_valuation_rate = SENTINEL_VALUATION
					row.valuation_rate = SENTINEL_VALUATION
				self._assert_absent(_render(doc, _inline(_format_html(fmt))))

	def test_the_field_itself_is_print_hide(self):
		_wed().setup_valuation_column()
		for doctype in ITEM_DOCTYPES:
			self.assertEqual(cint(frappe.get_meta(doctype).get_field("custom_valuation_rate").print_hide), 1)


class TestRow13Script(FrappeTestCase):
	def setUp(self):
		self.js = _source("public/js/price_assist.js")

	def test_the_grid_button_is_renamed_behind_the_switch(self):
		self.assertIn('"Show Sales History"', self.js)
		self.assertIn(R13, self.js)
		self.assertIn("yht_custom.price.open_sales_history", self.js)
		self.assertIn("get_history_popup", self.js)
		self.assertIn("render_assist_block", self.js)

	def test_the_price_assist_button_stays_and_double_click_on_rate_stays_off(self):
		self.assertIn('__("Price Assist")', self.js)
		self.assertIn("rate_shortcut_disabled()", self.js)
		self.assertIn("cr_019_no_rate_doubleclick", self.js)

	def test_the_valuation_cell_listener_is_capture_phase_and_names_the_field(self):
		self.assertRegex(self.js, r"closest\([^)]*custom_valuation_rate")
		self.assertIn("get_valuation_rates", self.js)
		# a capture-phase listener is registered at least twice now (rate + valuation cell)
		self.assertGreaterEqual(len(re.findall(r"addEventListener\(", self.js)), 2)
		self.assertGreaterEqual(len(re.findall(r"\},\s*true\s*,?\s*\)", self.js)), 2)

	def test_the_valuation_is_filled_on_item_change_only_never_on_refresh(self):
		self.assertNotRegex(self.js, r"refresh\s*\([^)]*\)\s*\{[^}]{0,400}get_valuation_rates")
		self.assertNotRegex(self.js, r"refresh_field\([^)]*custom_valuation_rate")
		self.assertIn("custom_valuation_rate", self.js)
		for doctype in ITEM_DOCTYPES:
			self.assertIn(f'frappe.ui.form.on("{doctype}"', self.js)

	def test_the_comparison_buttons_only_render_on_a_draft_and_cells_are_escaped(self):
		self.assertIn("docstatus === 0", self.js)
		self.assertIn("escape_html", self.js)
		self.assertIn("encodeURIComponent", self.js)


# ======================================================================= row 26


def _a_disabled_year():
	return frappe.db.get_value("Fiscal Year", {"disabled": 1}, "name")


def _an_enabled_year():
	return frappe.db.get_value("Fiscal Year", {"disabled": 0}, "name", order_by="year_start_date asc")


@contextlib.contextmanager
def _own_year(year, user=None):
	"""A user default for `fiscal_year`, cleared afterwards — the defaults cache is NOT rolled back."""
	user = user or frappe.session.user
	frappe.defaults.clear_user_default("fiscal_year", user=user)
	if year:
		frappe.defaults.set_user_default("fiscal_year", year, user=user)
	try:
		yield
	finally:
		frappe.defaults.clear_user_default("fiscal_year", user=user)
		frappe.clear_cache(user=user)


class TestRow26ChosenYear(FrappeTestCase):
	def setUp(self):
		self.year = _an_enabled_year()
		if not self.year:
			self.skipTest("no enabled Fiscal Year")

	def test_off_returns_empty_whatever_is_stored(self):
		with _own_year(self.year), _off(R26):
			self.assertEqual(_sy().chosen_year(), "")

	def test_an_enabled_year_is_returned(self):
		with _own_year(self.year):
			self.assertEqual(_sy().chosen_year(), self.year)
			self.assertEqual(_sy().chosen_year(frappe.session.user), self.year)

	def test_no_choice_is_empty(self):
		with _own_year(None):
			self.assertEqual(_sy().chosen_year(), "")

	def test_a_disabled_or_missing_year_is_ignored(self):
		disabled = _a_disabled_year()
		for bad in filter(None, (disabled, "9999-ZQXTEST")):
			with self.subTest(year=bad), _own_year(bad):
				self.assertEqual(_sy().chosen_year(), "")

	def test_a_list_default_uses_the_first_element(self):
		with mock.patch.object(
			frappe.defaults, "get_defaults_for", return_value={"fiscal_year": [self.year, "2000"]}
		):
			self.assertEqual(_sy().chosen_year(), self.year)

	def test_only_the_users_own_rows_are_read_never_a_global_default(self):
		with mock.patch.object(frappe.defaults, "get_defaults_for", return_value={}) as own, mock.patch.object(
			frappe.defaults, "get_user_default", return_value=self.year
		):
			self.assertEqual(_sy().chosen_year(), "")
		own.assert_called()

	def test_choices_are_enabled_years_newest_first(self):
		choices = _sy().fiscal_year_choices()
		expected = frappe.get_all(
			"Fiscal Year", filters={"disabled": 0}, order_by="year_start_date desc", pluck="name"
		)
		self.assertEqual(choices, expected)
		disabled = _a_disabled_year()
		if disabled:
			self.assertNotIn(disabled, choices)

	def test_default_fiscal_year_prefers_the_session_year(self):
		from yht_custom import list_defaults

		with _own_year(self.year):
			self.assertEqual(list_defaults.default_fiscal_year(), self.year)
		with _own_year(None):
			self.assertEqual(list_defaults.default_fiscal_year(), list_defaults.current_fiscal_year())
		with _own_year(self.year), _off(R26):
			self.assertEqual(list_defaults.default_fiscal_year(), list_defaults.current_fiscal_year())


class TestRow26Boot(FrappeTestCase):
	def setUp(self):
		self.year = _an_enabled_year()
		if not self.year:
			self.skipTest("no enabled Fiscal Year")
		self.boot = _mod("yht_custom.boot")

	def _boot(self):
		bootinfo = frappe._dict()
		self.boot.boot_session(bootinfo)
		return bootinfo

	def test_with_a_choice_boot_follows_it_and_stops_prompting(self):
		with _own_year(self.year):
			info = self._boot()
		self.assertEqual(info.yht_current_fiscal_year, self.year)
		self.assertTrue(info.yht_session_year["enabled"])
		self.assertFalse(info.yht_session_year["needs_prompt"])
		self.assertEqual(info.yht_session_year["current"], self.year)

	def test_without_a_choice_the_user_is_prompted_once(self):
		from yht_custom import list_defaults

		with _own_year(None):
			info = self._boot()
		session = info.yht_session_year
		self.assertTrue(session["needs_prompt"])
		self.assertEqual(session["current"], list_defaults.current_fiscal_year())
		self.assertEqual(session["choices"], _sy().fiscal_year_choices())
		self.assertIsInstance(session["companies"], list)

	def test_off_the_old_key_is_unchanged_and_the_new_one_is_empty(self):
		from yht_custom import list_defaults

		with _own_year(self.year), _off(R26):
			info = self._boot()
		self.assertEqual(info.yht_current_fiscal_year, list_defaults.current_fiscal_year())
		self.assertEqual(info.yht_session_year, {})

	def test_a_failure_in_the_new_code_never_breaks_boot(self):
		from yht_custom import list_defaults

		with mock.patch.object(list_defaults, "default_fiscal_year", side_effect=RuntimeError("boom")):
			info = self._boot()  # must not raise: /login boots every session
		self.assertEqual(info.yht_current_fiscal_year, "")
		self.assertIn("yht_features", info)  # the blocks below it still ran

	def test_the_branch_user_boots_with_the_new_keys_above_the_early_returns(self):
		if not frappe.db.exists("User", BRANCH_USER):
			self.skipTest("branch test user not present")
		with _own_year(self.year, user=BRANCH_USER), _as_user(BRANCH_USER):
			info = self._boot()
		self.assertEqual(info.yht_current_fiscal_year, self.year)
		self.assertIn("yht_session_year", info)
		self.assertTrue(info.get("yht_branch_restricted"))  # the old trimming still happens


class TestRow26SavedFilters(FrappeTestCase):
	"""A list default becomes a SAVED filter on first render, so the saved clause must follow."""

	DOCTYPE = "Sales Invoice"

	def setUp(self):
		from frappe.model.utils import user_settings

		self.us = user_settings
		self.user = frappe.session.user
		self.key = f"{self.DOCTYPE}::{self.user}"
		self.original = _cache().hget("_user_settings", self.key)
		years = frappe.get_all("Fiscal Year", filters={"disabled": 0}, order_by="year_start_date", pluck="name")
		if len(years) < 2:
			self.skipTest("need two enabled fiscal years")
		self.old, self.new = years[0], years[-1]

	def tearDown(self):
		if self.original is None:
			_cache().hdel("_user_settings", self.key)
		else:
			_cache().hset("_user_settings", self.key, self.original)

	def _seed(self, filters):
		self.us.update_user_settings(self.DOCTYPE, {"List": {"filters": filters}})

	def _filters(self):
		return json.loads(self.us.get_user_settings(self.DOCTYPE))["List"]["filters"]

	def test_a_stale_year_clause_is_rewritten_to_the_session_year(self):
		self._seed([[self.DOCTYPE, "custom_fiscal_year", "=", self.old], [self.DOCTYPE, "customer", "=", "X"]])
		_sy().sync_saved_filters(self.user, self.new)
		self.assertEqual(
			self._filters(),
			[[self.DOCTYPE, "custom_fiscal_year", "=", self.new], [self.DOCTYPE, "customer", "=", "X"]],
		)

	def test_a_list_with_no_year_clause_is_left_alone(self):
		clause = [[self.DOCTYPE, "customer", "=", "X"]]
		self._seed(clause)
		_sy().sync_saved_filters(self.user, self.new)
		self.assertEqual(self._filters(), clause)

	def test_a_second_call_writes_nothing(self):
		self._seed([[self.DOCTYPE, "custom_fiscal_year", "=", self.old]])
		_sy().sync_saved_filters(self.user, self.new)
		with mock.patch.object(self.us, "update_user_settings") as write:
			_sy().sync_saved_filters(self.user, self.new)
		write.assert_not_called()
		self.assertEqual(self._filters(), [[self.DOCTYPE, "custom_fiscal_year", "=", self.new]])

	def test_a_corrupt_blob_never_raises(self):
		_cache().hset("_user_settings", self.key, "{not json")
		_sy().sync_saved_filters(self.user, self.new)

	def test_every_fiscal_year_doctype_is_covered(self):
		from yht_custom import fiscal_year

		for doctype in fiscal_year.DATE_FIELD:
			with self.subTest(doctype=doctype):
				key = f"{doctype}::{self.user}"
				before = _cache().hget("_user_settings", key)
				try:
					self.us.update_user_settings(
						doctype, {"List": {"filters": [[doctype, "custom_fiscal_year", "=", self.old]]}}
					)
					_sy().sync_saved_filters(self.user, self.new)
					saved = json.loads(self.us.get_user_settings(doctype))["List"]["filters"]
					self.assertEqual(saved[0][3], self.new)
				finally:
					if before is None:
						_cache().hdel("_user_settings", key)
					else:
						_cache().hset("_user_settings", key, before)

	def test_boot_runs_it_once_when_a_year_is_chosen(self):
		self._seed([[self.DOCTYPE, "custom_fiscal_year", "=", self.old]])
		with _own_year(self.new):
			_mod("yht_custom.boot").boot_session(frappe._dict())
		self.assertEqual(self._filters(), [[self.DOCTYPE, "custom_fiscal_year", "=", self.new]])

	def test_boot_without_a_choice_leaves_saved_filters_alone(self):
		self._seed([[self.DOCTYPE, "custom_fiscal_year", "=", self.old]])
		with _own_year(None):
			_mod("yht_custom.boot").boot_session(frappe._dict())
		self.assertEqual(self._filters(), [[self.DOCTYPE, "custom_fiscal_year", "=", self.old]])


class TestRow26Provisioning(FrappeTestCase):
	def _rows(self):
		return [
			r.ref_doctype
			for r in frappe.get_single("Session Default Settings").session_defaults
		]

	def test_the_fiscal_year_row_exists_once_after_two_runs(self):
		_sy().setup_session_year()
		_sy().setup_session_year()
		self.assertEqual(self._rows().count("Fiscal Year"), 1)

	def test_off_adds_nothing(self):
		with _off(R26):
			self.assertIn("skipped", _sy().setup_session_year())

	def test_branch_roles_can_read_fiscal_year_and_nobody_else_loses_access(self):
		"""The browser pass found "You do not have Read or Select Permissions for Fiscal
		Year" on every list a branch user opened: the Fiscal Year filter is a Link control
		and validates its value. The grant mirrors the standard rows first (gotcha 6)."""
		standard = {
			(r.role, r.permlevel): r.read
			for r in frappe.get_all("DocPerm", filters={"parent": "Fiscal Year"}, fields=["role", "permlevel", "read"])
		}
		before = frappe.db.count("Custom DocPerm", {"parent": "Fiscal Year"})
		_sy().setup_session_year()
		for role in ("Branch User", "Branch Manager"):
			row = frappe.db.get_value(
				"Custom DocPerm", {"parent": "Fiscal Year", "role": role, "permlevel": 0}, ["read", "write", "create", "delete"], as_dict=True
			)
			self.assertTrue(row, role)
			self.assertEqual((row.read, row.write, row.create, row.delete), (1, 0, 0, 0), role)
		if not before:
			# every standard role keeps what it had
			for (role, level), read in standard.items():
				got = frappe.db.get_value("Custom DocPerm", {"parent": "Fiscal Year", "role": role, "permlevel": level}, "read")
				self.assertEqual(got, read, role)

	def test_the_grant_is_idempotent_and_off_writes_nothing(self):
		_sy().setup_session_year()
		count = frappe.db.count("Custom DocPerm", {"parent": "Fiscal Year"})
		_sy().setup_session_year()
		self.assertEqual(frappe.db.count("Custom DocPerm", {"parent": "Fiscal Year"}), count)
		with _off(R26):
			before = frappe.db.count("Custom DocPerm", {"parent": "Fiscal Year"})
			_sy().setup_session_year()
			self.assertEqual(frappe.db.count("Custom DocPerm", {"parent": "Fiscal Year"}), before)

	def test_a_branch_user_can_read_fiscal_year_after_the_step(self):
		user = "branchtest@yht-khobhar.enfonoerp.com"
		if not frappe.db.exists("User", user):
			self.skipTest("branch test user not present")
		_sy().setup_session_year()
		frappe.clear_cache(user=user)
		self.assertTrue(frappe.has_permission("Fiscal Year", "read", user=user))
		self.assertFalse(frappe.has_permission("Fiscal Year", "write", user=user))

	def test_logout_clears_the_chosen_year_because_the_row_exists(self):
		from frappe.core.doctype.session_default_settings.session_default_settings import (
			clear_session_defaults,
		)

		_sy().setup_session_year()
		year = _an_enabled_year()
		with _own_year(year):
			self.assertEqual(frappe.defaults.get_defaults_for(frappe.session.user).get("fiscal_year"), year)
			clear_session_defaults()
			self.assertFalse(frappe.defaults.get_defaults_for(frappe.session.user).get("fiscal_year"))


class TestRow26NewFormYear(FrappeTestCase):
	"""A Link to Fiscal Year takes the session default on a new document, so a form dated
	today opened showing the SESSION year under a note saying it is derived from the date."""

	def test_the_script_clears_the_year_on_a_new_draft_of_all_eight(self):
		source = (ROOT / "public/js/session_year.js").read_text()
		self.assertIn('frm.is_new() && frm.doc.custom_fiscal_year', source)
		self.assertIn('"oct11_r26_session_fiscal_year"', source)
		for doctype in ("Sales Invoice", "Purchase Invoice", "Delivery Note", "Purchase Receipt", "Payment Entry", "Journal Entry", "Sales Order", "Quotation"):
			self.assertIn(f'"{doctype}"', source, doctype)

	def test_the_eight_match_the_doctypes_that_carry_the_field(self):
		from yht_custom import fiscal_year

		source = (ROOT / "public/js/session_year.js").read_text()
		for doctype in fiscal_year.DATE_FIELD:
			self.assertIn(f'"{doctype}"', source, doctype)

	def test_the_cache_buster_was_bumped(self):
		self.assertIn("session_year.js?v=2", (ROOT / "hooks.py").read_text())


class TestRow26Script(FrappeTestCase):
	def setUp(self):
		self.js = _source("public/js/session_year.js")

	def test_it_is_registered_with_a_version(self):
		self.assertIn("/assets/yht_custom/js/session_year.js?v=2", _source("hooks.py"))

	def test_it_is_inert_when_off_or_when_no_prompt_is_needed(self):
		self.assertIn(R26, self.js)
		self.assertIn("needs_prompt", self.js)
		self.assertIn("yht_session_year", self.js)
		self.assertIn("app_ready", self.js)

	def test_the_flag_is_set_before_the_dialog_is_shown(self):
		flag = self.js.index("yht_session_year_shown")
		self.assertIn("sessionStorage", self.js)
		self.assertLess(self.js.index("sessionStorage.setItem"), self.js.index("new frappe.ui.Dialog"))
		self.assertLess(flag, self.js.index("new frappe.ui.Dialog"))

	def test_the_dialog_uses_a_select_and_franes_own_method(self):
		self.assertIn('fieldtype: "Select"', self.js)
		self.assertNotRegex(self.js, r'options:\s*"Fiscal Year"')  # Branch User cannot read Fiscal Year
		self.assertIn(
			"frappe.core.doctype.session_default_settings.session_default_settings.set_session_default_values",
			self.js,
		)
		self.assertIn("default_values", self.js)
		self.assertIn("frappe.ui.toolbar.clear_cache", self.js)
		self.assertIn("companies.length > 1", self.js)

	def test_the_method_it_calls_is_whitelisted_in_frappe_core(self):
		method = frappe.get_attr(
			"frappe.core.doctype.session_default_settings.session_default_settings.set_session_default_values"
		)
		self.assertIn(method, frappe.whitelisted)

	def test_list_defaults_js_needs_no_change(self):
		self.assertNotIn("session_year", _source("public/js/list_defaults.js"))


# ======================================================================= row 30


class _OrderHarness:
	"""Serve `_live_order` from a dict and let `_write_order` update it, so the
	live Delivery Note / Sales Invoice shapes can be tested without a site that has them."""

	def __init__(self, overrides):
		self.orders = {k: list(v) for k, v in overrides.items()}
		self.writes = []
		wed, m1011 = _wed(), _mod("yht_custom.meeting_1011")
		self._real = m1011._live_order
		self.stack = contextlib.ExitStack()
		for target in (m1011, wed):
			self.stack.enter_context(mock.patch.object(target, "_live_order", side_effect=self.live, create=True))
		for target in (_mod("yht_custom.field_layout"), wed):
			self.stack.enter_context(mock.patch.object(target, "_write_order", side_effect=self.write, create=True))
		self.stack.enter_context(
			mock.patch.object(_mod("yht_custom.field_layout"), "_read_order", return_value=(None, []))
		)

	def live(self, doctype):
		if doctype not in self.orders:
			self.orders[doctype] = list(self._real(doctype))
		return list(self.orders[doctype])

	def write(self, doctype, ps_name, order):
		self.orders[doctype] = list(order)
		self.writes.append(doctype)

	def __enter__(self):
		return self

	def __exit__(self, *exc):
		self.stack.close()


BLOCK_A = ["custom_front_party_section", "customer_address", "address_display", "custom_front_party_col",
           "contact_person", "contact_display"]
BLOCK_B = ["custom_front_team_section", "sales_team"]

# The measured live Delivery Note: the client re-laid it out, `section_break1` heads the item table.
LIVE_DN = ["custom_section_break_ljol1", "customer", "customer_name", "tax_id", "po_no", "po_date",
           "section_break1", "items", "set_posting_time", "customer_address", "address_display",
           "contact_person", "contact_display", "sales_team", "custom_front_party_section",
           "custom_front_party_col", "custom_front_team_section"]
# The measured live Sales Invoice: po_no / po_date live in the More Info tab, behind the items.
LIVE_SI = ["naming_series", "customer", "customer_name", "tax_id", "posting_date", "due_date", "items_section",
           "items", "more_info_tab", "po_no", "po_date", "customer_address", "address_display",
           "contact_person", "contact_display", "sales_team", "custom_front_party_section",
           "custom_front_party_col", "custom_front_team_section"]


class TestRow30Layout(FrappeTestCase):
	def setUp(self):
		self.before = {d: _fieldnames(d) for d in SELLING}
		_wed().setup_front_details()

	def _tab_of(self, doctype, fieldname):
		order, tab = frappe.get_meta(doctype).fields, None
		for df in order:
			if df.fieldtype == "Tab Break":
				tab = df.fieldname
			if df.fieldname == fieldname:
				return tab
		return None

	def test_every_moved_field_sits_in_the_front_before_the_item_table(self):
		from yht_custom import meeting_1011

		for doctype in SELLING:
			with self.subTest(doctype=doctype):
				order = _fieldnames(doctype)
				boundary = meeting_1011._front_boundary(order)
				names = BLOCK_A + (BLOCK_B if doctype != "Quotation" else [])
				for name in names:
					self.assertLess(order.index(name), boundary, f"{doctype}.{name}")

	def test_the_four_address_and_contact_fields_are_in_the_first_tab(self):
		for doctype in SELLING:
			with self.subTest(doctype=doctype):
				anchor = "customer" if "customer" in _fieldnames(doctype) else "party_name"
				for name in ("customer_address", "address_display", "contact_person", "contact_display"):
					self.assertEqual(self._tab_of(doctype, name), self._tab_of(doctype, anchor), name)

	def test_nothing_is_dropped_and_only_the_layout_breaks_are_new(self):
		for doctype in SELLING:
			with self.subTest(doctype=doctype):
				after = _fieldnames(doctype)
				self.assertEqual(len(after), len(set(after)))
				self.assertLessEqual(set(self.before[doctype]), set(after))
				added = set(after) - set(self.before[doctype])
				self.assertLessEqual(added, {"custom_front_party_section", "custom_front_party_col",
				                              "custom_front_team_section"})

	def test_the_new_fields_are_exactly_the_three_layout_breaks(self):
		expected = {
			"custom_front_party_section": "Section Break",
			"custom_front_party_col": "Column Break",
			"custom_front_team_section": "Section Break",
		}
		for doctype in SELLING:
			with self.subTest(doctype=doctype):
				meta = frappe.get_meta(doctype)
				found = {f.fieldname: f.fieldtype for f in meta.fields if f.fieldname.startswith("custom_front_")}
				want = dict(expected)
				if doctype == "Quotation":
					want.pop("custom_front_team_section")
				self.assertEqual(found, want)

	def test_the_team_section_is_collapsible_and_sits_directly_before_sales_team(self):
		for doctype in ("Sales Order", "Sales Invoice", "Delivery Note"):
			with self.subTest(doctype=doctype):
				order = _fieldnames(doctype)
				self.assertEqual(order.index("custom_front_team_section") + 1, order.index("sales_team"))
				self.assertEqual(cint(frappe.get_meta(doctype).get_field("custom_front_team_section").collapsible), 1)

	def test_quotation_gets_address_and_contact_only(self):
		meta = frappe.get_meta("Quotation")
		for name in ("sales_team", "po_no", "po_date", "custom_front_team_section"):
			self.assertIsNone(meta.get_field(name), name)

	def test_po_fields_are_on_the_front_of_the_three_documents_that_carry_them(self):
		from yht_custom import meeting_1011

		for doctype in ("Sales Order", "Sales Invoice", "Delivery Note"):
			with self.subTest(doctype=doctype):
				order = _fieldnames(doctype)
				boundary = meeting_1011._front_boundary(order)
				self.assertLess(order.index("po_no"), boundary)
				self.assertLess(order.index("po_date"), boundary)

	def test_fields_that_stay_behind_stay_behind(self):
		from yht_custom import meeting_1011

		for doctype in ("Sales Order", "Sales Invoice"):
			order = _fieldnames(doctype)
			boundary = meeting_1011._front_boundary(order)
			for name in ("commission_rate", "total_commission", "sales_partner"):
				if name in order:
					self.assertGreater(order.index(name), boundary, f"{doctype}.{name}")

	def test_a_second_run_changes_nothing_and_writes_nothing(self):
		before = {d: _fieldnames(d) for d in SELLING}
		with contextlib.ExitStack() as stack:
			writes = [
				stack.enter_context(mock.patch.object(_mod("yht_custom.field_layout"), "_write_order")),
				stack.enter_context(mock.patch.object(_wed(), "_write_order", create=True)),
			]
			_wed().setup_front_details()
		for mocked in writes:
			mocked.assert_not_called()
		self.assertEqual(before, {d: _fieldnames(d) for d in SELLING})

	def test_the_steps_converge_in_either_order(self):
		"""Gotcha 127 — heading, tick and the new block all place against the front page."""
		from yht_custom import meeting_1011

		steps = (meeting_1011.setup_heading_front, meeting_1011.setup_print_with_arabic, _wed().setup_front_details)
		for ordering in (steps, tuple(reversed(steps))):
			for _ in range(2):
				for step in ordering:
					step()
		first = {d: _fieldnames(d) for d in SELLING}
		for step in steps:
			step()
		for step in reversed(steps):
			step()
		self.assertEqual(first, {d: _fieldnames(d) for d in SELLING})

	def test_off_creates_nothing_and_writes_nothing(self):
		with _off(R30), mock.patch(
			"frappe.custom.doctype.custom_field.custom_field.create_custom_fields"
		) as create, mock.patch.object(_mod("yht_custom.field_layout"), "_write_order") as write:
			result = _wed().setup_front_details()
		self.assertIn("skipped", result)
		create.assert_not_called()
		write.assert_not_called()


class TestRow30LiveShapes(FrappeTestCase):
	"""The two live layouts that differ from UAT (spec §2 row 30)."""

	def test_the_live_delivery_note_block_goes_before_section_break1_not_inside_the_items_section(self):
		with _OrderHarness({"Delivery Note": LIVE_DN}) as harness:
			_wed().setup_front_details()
		order = harness.orders["Delivery Note"]
		self.assertEqual(sorted(order), sorted(LIVE_DN))  # a permutation: nothing lost, nothing added
		self.assertEqual(order[order.index("custom_front_party_section"):][:6], BLOCK_A)
		self.assertEqual(order.index("section_break1") + 1, order.index("items"))
		self.assertLess(order.index("custom_front_party_section"), order.index("section_break1"))
		self.assertLess(order.index("sales_team"), order.index("section_break1"))
		self.assertLess(order.index("po_no"), order.index("section_break1"))

	def test_the_live_sales_invoice_po_fields_are_pulled_to_the_front_under_the_party_anchor(self):
		with _OrderHarness({"Sales Invoice": LIVE_SI}) as harness:
			_wed().setup_front_details()
		order = harness.orders["Sales Invoice"]
		self.assertEqual(sorted(order), sorted(LIVE_SI))
		self.assertEqual(order.index("po_no"), order.index("tax_id") + 1)
		self.assertEqual(order.index("po_date"), order.index("po_no") + 1)
		self.assertLess(order.index("po_date"), order.index("items_section"))
		self.assertLess(order.index("custom_front_party_section"), order.index("items_section"))

	def test_the_po_anchor_candidates_mirror_front_anchors(self):
		wed = _wed()
		self.assertEqual(tuple(wed.PO_ANCHORS), ("tax_id", "customer_name", "customer"))

	def test_place_block_is_idempotent_on_a_converged_order(self):
		with _OrderHarness({"Delivery Note": LIVE_DN}) as harness:
			_wed().setup_front_details()
			first = list(harness.orders["Delivery Note"])
			harness.writes.clear()
			_wed().setup_front_details()
		self.assertEqual(first, harness.orders["Delivery Note"])
		self.assertEqual(harness.writes, [])


class TestRow30Prints(FrappeTestCase):
	ADDR, CONTACT, PO, PODATE = "ZQXADDRLINE", "ZQXCONTACT", "ZQXPO1", "2031-07-09"

	CASES = {
		# format file -> (doctype, new sentinel cells expected ON, existing cells that must appear once)
		"katc_quotation": ("Quotation", {"addr": 1}, {"contact": 1}),
		"katc_sales_order": ("Sales Order", {"addr": 1, "contact": 1, "podate": 1, "exec": 1}, {}),
		"katc_proforma_invoice": ("Sales Order", {"contact": 1, "podate": 1}, {"addr": 1}),
		"katc_tax_invoice": ("Sales Invoice", {"contact": 1, "podate": 1}, {}),
		"katc_delivery_note": ("Delivery Note", {"po": 1, "podate": 1, "contact": 1, "exec": 1}, {"addr": 1}),
	}

	def _doc(self, doctype):
		doc = _a_doc(doctype)
		if not doc:
			self.skipTest(f"no submitted {doctype} on this site")
		doc.address_display = self.ADDR
		doc.contact_display = self.CONTACT
		doc.po_no = self.PO
		doc.po_date = self.PODATE
		if doctype == "Quotation":
			doc.custom_print_as = "Sales Quotation"
			doc.select_print_heading = "Sales Quotation"
		return doc

	def _counts(self, out):
		return {
			"addr": out.count(self.ADDR),
			"contact": out.count(self.CONTACT),
			"po": out.count(self.PO),
			"podate": out.count("2031"),
			"exec": out.lower().count("sales executive"),
		}

	def test_every_touched_source_is_bracketed_and_gated(self):
		sources = {
			"katc_quotation": "templates/includes/katc/quotation.html",
			"katc_sales_order": "templates/includes/katc/sales_order.html",
			"katc_proforma_invoice": "templates/includes/katc/proforma_invoice.html",
			"katc_tax_invoice": f"yht_custom/print_format/katc_tax_invoice/katc_tax_invoice.json",
			"katc_delivery_note": f"yht_custom/print_format/katc_delivery_note/katc_delivery_note.json",
		}
		for fmt, path in sources.items():
			with self.subTest(source=path):
				text = _source(path)
				if path.endswith(".json"):
					text = json.loads(text)["html"]
				markers = text.count("{# r30 #}")
				self.assertGreaterEqual(markers, 2)
				self.assertEqual(markers % 2, 0, "markers come in open/close pairs")
				stripped_away = text.split("{# r30 #}")[1::2]  # the text INSIDE each bracket
				for chunk in stripped_away:
					self.assertIn(R30, chunk)
					self.assertIn("yht_feature", chunk)

	def test_on_the_missing_cells_appear_and_the_existing_ones_appear_once(self):
		for fmt, (doctype, new, existing) in self.CASES.items():
			with self.subTest(format=fmt):
				doc = self._doc(doctype)
				counts = self._counts(_render(doc, _inline(_format_html(fmt))))
				for key, minimum in new.items():
					self.assertGreaterEqual(counts[key], minimum, f"{fmt}: {key} missing")
				for key, exactly in existing.items():
					self.assertEqual(counts[key], exactly, f"{fmt}: {key} duplicated or missing")
				for key in ("addr", "contact"):
					self.assertLessEqual(counts[key], 1, f"{fmt}: {key} printed twice")

	def test_the_quotation_proforma_renders_no_undefined_marker(self):
		"""Gotcha 77: the shared proforma include serves a Quotation too, and DebugUndefined
		prints `{{ doc.po_date }}` onto a customer-facing PDF."""
		doc = self._doc("Quotation")
		out = _render(doc, _inline(_format_html("katc_proforma_invoice")), print_format_doctype="Quotation")
		self.assertNotIn("{{", out)
		self.assertNotIn("{%", out)
		self.assertNotIn("Undefined", out)
		self.assertEqual(out.count(self.CONTACT), 1)
		self.assertEqual(out.count(self.ADDR), 1)

	def test_off_is_byte_identical_to_the_template_without_the_r30_lines(self):
		for fmt, (doctype, _new, _existing) in self.CASES.items():
			with self.subTest(format=fmt):
				doc = self._doc(doctype)
				html = _inline(_format_html(fmt))
				self.assertIn("{# r30 #}", html)
				with _off(R30):
					off = _render(doc, html)
					baseline = _render(doc, _strip_r30(html))
				self.assertEqual(off, baseline)
				counts = self._counts(off)
				_doctype, new, _ = self.CASES[fmt]
				for key in new:
					self.assertEqual(counts[key], 0, f"{fmt}: {key} leaked with the switch off")

	def test_the_json_formats_carry_a_newer_modified_so_import_file_applies_them(self):
		for fmt in ("katc_tax_invoice", "katc_delivery_note"):
			with self.subTest(format=fmt):
				modified = json.loads(_source(f"yht_custom/print_format/{fmt}/{fmt}.json"))["modified"]
				self.assertGreater(modified, "2026-10-01 11:00:00")

	def test_no_new_jinja_method_is_registered(self):
		"""Gotcha 25 / 102: a new jinja hook 500s /login until the shared worker pool reloads."""
		jinja = frappe.get_hooks("jinja", app_name="yht_custom") or {}
		methods = " ".join(str(m) for m in (jinja.get("methods") or []))
		for banned in ("front_details", "r30", "wednesday"):
			self.assertNotIn(banned, methods)

	def test_the_item_grid_widths_in_the_katc_formats_are_not_touched(self):
		"""Gotcha 116: additive markup goes in the meta table, never the katc-items widths."""
		for fmt in ("katc_tax_invoice", "katc_delivery_note"):
			html = _format_html(fmt)
			gated = "".join(html.split("{# r30 #}")[1::2])
			self.assertNotIn("katc-items", gated)
			self.assertNotRegex(gated, r"width\s*:\s*\d")


# ======================================================================= row 32


def _upstream_sentinel():
	return [{"doctype": "ZQX", "name": "UPSTREAM-ONLY", "content": "x", "rank": 1.0}]


def _desk_search(text, **extra):
	"""The desk's real path (gotcha 118): `/api/method/…` → `handler.execute_cmd`."""
	import frappe.handler

	cmd = "frappe.utils.global_search.search"
	had_request = getattr(frappe.local, "request", None)
	saved_form = frappe.local.form_dict
	frappe.local.form_dict = frappe._dict(cmd=cmd, text=text, **extra)
	frappe.local.request = frappe._dict(method="GET", path=f"/api/method/{cmd}")
	try:
		return frappe.handler.execute_cmd(cmd)
	finally:
		frappe.local.form_dict = saved_form
		if had_request is None:
			with contextlib.suppress(Exception):
				del frappe.local.request
		else:
			frappe.local.request = had_request


def _prefix_block(results):
	return [r for r in results if r.get("rank") == 1000]


class TestRow32DocNumberSearch(FrappeTestCase):
	def setUp(self):
		if not frappe.db.count("Sales Invoice", {"name": ["like", "KSIN-%"]}):
			self.skipTest("no KSIN- invoices on this site")

	def test_the_desks_own_path_reaches_the_override(self):
		self.assertEqual(
			frappe.override_whitelisted_method("frappe.utils.global_search.search"),
			"yht_custom.doc_number_search.search",
		)
		results = _desk_search("KSIN")
		prefix = _prefix_block(results)
		self.assertTrue(prefix, "no prefix block: the override did not run on the desk path")
		self.assertTrue(results[0]["name"].startswith("KSIN-"))

	def test_prefix_hits_are_newest_first_capped_and_ranked_above_upstream(self):
		results = _desk_search("KSIN")
		self.assertLessEqual(len(results), 20)
		prefix = _prefix_block(results)
		names = [r["name"] for r in prefix]
		self.assertEqual(names, sorted(names, reverse=True))
		self.assertEqual(results[: len(prefix)], prefix)  # the prefix block is FIRST
		seen = [(r["doctype"], r["name"]) for r in results]
		self.assertEqual(len(seen), len(set(seen)))  # upstream hits already shown are not repeated

	def test_an_exact_full_number_is_first(self):
		name = frappe.db.get_value("Sales Invoice", {"name": ["like", "KSIN-%"]}, "name", order_by="name desc")
		if not frappe.db.sql("SELECT 1 FROM `__global_search` WHERE doctype='Sales Invoice' AND name=%s", (name,)):
			self.skipTest("the newest invoice is not indexed in __global_search on this site")
		results = _desk_search(name)
		self.assertEqual(results[0]["name"], name)
		self.assertEqual(results[0]["doctype"], "Sales Invoice")

	def test_the_result_shape_is_upstreams_so_the_search_dialog_can_consume_it(self):
		for row in _desk_search("KSIN"):
			self.assertTrue({"doctype", "name", "content", "rank"} <= set(row))

	def test_matching_is_case_insensitive_and_that_is_documented_not_hidden(self):
		upper = _prefix_block(_desk_search("KSIN"))
		lower = _prefix_block(_desk_search("ksin"))
		self.assertTrue(upper)
		self.assertEqual(upper[0]["name"], lower[0]["name"])
		self.assertIn("case", pathlib.Path(_dns().__file__).read_text().lower())

	def test_like_wildcards_in_the_text_are_escaped(self):
		with mock.patch("frappe.utils.global_search.search", return_value=[]):
			self.assertEqual(_prefix_block(_dns().search("K_IN")), [])
			self.assertEqual(_prefix_block(_dns().search("K%N-")), [])

	def test_a_branch_user_is_never_handed_a_number_they_cannot_read(self):
		if not frappe.db.exists("User", BRANCH_USER):
			self.skipTest("branch test user not present")
		names = frappe.get_all("Sales Invoice", filters={"name": ["like", "KSIN-%"]}, pluck="name",
		                       order_by="name desc", limit=300)
		with _as_user(BRANCH_USER):
			visible = set(frappe.get_list("Sales Invoice", filters={"name": ["in", names]}, pluck="name"))
		hidden = [n for n in names if n not in visible and frappe.db.sql(
			"SELECT 1 FROM `__global_search` WHERE doctype='Sales Invoice' AND name=%s", (n,))]
		if not hidden:
			self.skipTest("the branch user can read every recent invoice")
		with _as_user(BRANCH_USER):
			results = _desk_search(hidden[0])
		self.assertNotIn(hidden[0], {r["name"] for r in _prefix_block(results)})


class TestRow32PassThrough(FrappeTestCase):
	"""Anything the override does not own is upstream's answer, untouched."""

	def _upstream_called(self, text="KSIN", off=False, **kwargs):
		with mock.patch("frappe.utils.global_search.search", return_value=_upstream_sentinel()) as up:
			if off:
				with _off(R32):
					out = _dns().search(text, **kwargs)
			else:
				out = _dns().search(text, **kwargs)
		return out, up

	def test_the_switch_off_returns_upstream_exactly(self):
		out, up = self._upstream_called(off=True)
		self.assertEqual(out, _upstream_sentinel())
		up.assert_called_once()

	def test_pagination_falls_through(self):
		out, up = self._upstream_called(start=20)
		self.assertEqual(out, _upstream_sentinel())
		up.assert_called_once()

	def test_text_that_is_not_one_document_token_falls_through(self):
		for text in ("KSIN 26", "KSIN&26", "a", "-KSIN", "KS$IN", "K" * 41, "", "KSIN-26/0001 x"):
			with self.subTest(text=text):
				out, up = self._upstream_called(text=text)
				self.assertEqual(out, _upstream_sentinel())
				up.assert_called_once()

	def test_the_override_calls_the_original_not_itself(self):
		"""The hook maps the NAME, so calling `global_search.search` is not recursion."""
		out, up = self._upstream_called(text="ZQXTEST-NOSUCH-0000")
		up.assert_called_once()
		self.assertEqual(out, _upstream_sentinel())  # no prefix hits: upstream untouched

	def test_the_signature_is_upstreams(self):
		import inspect

		from frappe.utils import global_search

		# frappe 15 validates whitelisted annotations: the override must match.
		self.assertEqual(
			list(inspect.signature(_dns().search).parameters),
			list(inspect.signature(global_search.search).parameters),
		)
		self.assertIn(_dns().search, frappe.whitelisted)


# ======================================================================= row 33


EXPENSE_FILTER_JSON = '{"custom_is_expense_invoice": 1}'


def _flag_filter_shortcuts(workspace):
	doc = frappe.get_doc("Workspace", workspace)
	return [r for r in doc.shortcuts if r.link_to == "Purchase Invoice" and "custom_is_expense_invoice" in (r.stats_filter or "")]


class TestRow33Shortcuts(FrappeTestCase):
	def setUp(self):
		# FrappeTestCase rolls back per CLASS (gotcha 50): drop what the earlier tests provisioned.
		frappe.db.delete("Workspace Shortcut", {"label": ["in", ["Record Expense", "Expense Invoices"]], "parent": ["in", ["Buying", "Accounting", "Home"]]})
		for workspace in ("Buying", "Accounting", "Home"):
			if frappe.db.exists("Workspace", workspace):
				frappe.clear_document_cache("Workspace", workspace)

	def _shortcuts(self, workspace):
		return {r.label: r for r in frappe.get_doc("Workspace", workspace).shortcuts}

	def test_record_expense_is_added_to_buying_and_accounting_as_a_new_form_with_the_flag(self):
		_mod("yht_custom.expense_invoice").setup_record_expense()
		for workspace in ("Buying", "Accounting"):
			with self.subTest(workspace=workspace):
				if not frappe.db.exists("Workspace", workspace):
					self.skipTest(f"no {workspace} workspace")
				row = self._shortcuts(workspace)["Record Expense"]
				self.assertEqual(row.type, "DocType")
				self.assertEqual(row.link_to, "Purchase Invoice")
				self.assertEqual(row.doc_view, "New")
				self.assertEqual(row.stats_filter, EXPENSE_FILTER_JSON)
				content = json.loads(frappe.db.get_value("Workspace", workspace, "content") or "[]")
				self.assertTrue(any(
					b.get("type") == "shortcut" and b.get("data", {}).get("shortcut_name") == "Record Expense"
					for b in content
				), "the layout half is missing: the shortcut would exist and show nowhere")

	def test_expense_invoices_list_is_added_to_accounting_and_never_to_the_branch_workspace(self):
		_mod("yht_custom.expense_invoice").setup_record_expense()
		if frappe.db.exists("Workspace", "Accounting"):
			row = self._shortcuts("Accounting")["Expense Invoices"]
			self.assertEqual(row.doc_view, "List")
			self.assertEqual(
				json.loads(row.stats_filter),
				[["Purchase Invoice", "custom_is_expense_invoice", "=", 1, False]],
			)
		if frappe.db.exists("Workspace", "Branch User"):  # unreachable for a branch user (gotcha 62)
			labels = self._shortcuts("Branch User")
			self.assertNotIn("Record Expense", labels)
			self.assertNotIn("Expense Invoices", labels)

	def test_the_existing_expense_invoice_shortcut_is_adopted_not_duplicated_or_renamed(self):
		before = {w: [r.label for r in _flag_filter_shortcuts(w) if r.doc_view == "List"]
		          for w in ("Buying", "Home") if frappe.db.exists("Workspace", w)}
		_mod("yht_custom.expense_invoice").setup_record_expense()
		for workspace, labels in before.items():
			after = [r.label for r in _flag_filter_shortcuts(workspace) if r.doc_view == "List"]
			if labels:
				self.assertEqual(sorted(after), sorted(l for l in labels), workspace)
				self.assertNotIn("Expense Invoices", self._shortcuts(workspace))

	def test_a_second_run_adds_nothing(self):
		step = _mod("yht_custom.expense_invoice").setup_record_expense
		step()
		snapshot = {w: sorted(self._shortcuts(w)) for w in ("Buying", "Accounting", "Home")
		            if frappe.db.exists("Workspace", w)}
		content = {w: frappe.db.get_value("Workspace", w, "content") for w in snapshot}
		step()
		self.assertEqual(snapshot, {w: sorted(self._shortcuts(w)) for w in snapshot})
		self.assertEqual(content, {w: frappe.db.get_value("Workspace", w, "content") for w in snapshot})

	def test_it_only_adds_never_removes_or_reorders(self):
		before = {w: [r.label for r in frappe.get_doc("Workspace", w).shortcuts]
		          for w in ("Buying", "Accounting") if frappe.db.exists("Workspace", w)}
		_mod("yht_custom.expense_invoice").setup_record_expense()
		for workspace, labels in before.items():
			after = [r.label for r in frappe.get_doc("Workspace", workspace).shortcuts]
			self.assertEqual(after[: len(labels)], labels)

	def test_off_writes_nothing(self):
		with _off(R33):
			self.assertIn("skipped", _mod("yht_custom.expense_invoice").setup_record_expense())
		self.assertFalse(frappe.db.exists("Workspace Shortcut", {"label": "Record Expense", "parent": "Buying"}))


class TestRow33Contracts(FrappeTestCase):
	def test_the_flag_survives_route_options_but_the_series_does_not(self):
		"""Why the series is set client-side: `create_new.js` skips no_copy fields."""
		meta = frappe.get_meta("Purchase Invoice")
		self.assertEqual(cint(meta.get_field("custom_is_expense_invoice").no_copy), 0)
		self.assertEqual(cint(meta.get_field("naming_series").no_copy), 1)

	def test_the_expense_series_is_asserted_by_exact_match_not_first_option(self):
		self.assertEqual(_mod("yht_custom.expense_invoice").EXPENSE_SERIES, "KSEPI-.YY.-.####")
		self.assertIn("KSEPI-.YY.-.####", (frappe.get_meta("Purchase Invoice").get_field("naming_series").options or "").split("\n"))

	def test_branch_roles_can_already_create_a_purchase_invoice(self):
		for role in ("Branch User", "Branch Manager"):
			row = frappe.db.get_value(
				"Custom DocPerm", {"parent": "Purchase Invoice", "role": role, "permlevel": 0},
				["create", "write", "read", "submit"], as_dict=True,
			)
			self.assertTrue(row, role)
			self.assertEqual((row.create, row.write, row.read), (1, 1, 1), role)

	def test_purchase_invoice_stays_in_the_branch_allow_list(self):
		"""Gotcha 7: the tile's destination is already allowed; this pins it so removal fails loudly."""
		self.assertRegex(_source("public/js/branch_user_restrict.js"), r'ALLOWED_DOCTYPES\s*=\s*\[[^\]]*"Purchase Invoice"')

	def test_the_backfill_dry_run_changes_nothing(self):
		before = frappe.db.count("Purchase Invoice", {"custom_is_expense_invoice": 0})
		result = _mod("yht_custom.expense_invoice").backfill_expense_flag(commit=False)
		self.assertFalse(result["committed"])
		self.assertEqual(frappe.db.count("Purchase Invoice", {"custom_is_expense_invoice": 0}), before)


class TestRow33BranchUserFlow(FrappeTestCase):
	def _new(self, user):
		company = frappe.db.get_value("Company", {}, "name")
		supplier = frappe.db.get_value("Supplier", {"disabled": 0}, "name")
		account = frappe.db.get_value(
			"Account", {"company": company, "root_type": "Expense", "is_group": 0, "disabled": 0}, "name"
		)
		cost_center = frappe.db.get_value("User Permission", {"user": BRANCH_USER, "allow": "Cost Center"}, "for_value")
		if not (supplier and account and cost_center):
			self.skipTest("site lacks a supplier / expense account / branch cost centre")
		with _as_user(user):
			doc = frappe.get_doc({
				"doctype": "Purchase Invoice", "company": company, "supplier": supplier,
				"custom_is_expense_invoice": 1, "posting_date": frappe.utils.today(),
				"bill_no": f"ZQXTEST-{frappe.generate_hash(length=8)}", "update_stock": 0,
				"items": [{"item_name": "ZQXTEST rent", "description": "ZQXTEST rent", "qty": 1, "rate": 10,
				           "expense_account": account, "cost_center": cost_center}],
			})
			doc.insert()
		return doc

	def test_a_branch_user_raises_an_expense_that_numbers_visibly_and_is_listed_for_them_only(self):
		if not frappe.db.exists("User", BRANCH_USER):
			self.skipTest("branch test user not present")
		_mod("yht_custom.expense_invoice").setup_record_expense()  # the entry points the user arrives through
		mine = self._new(BRANCH_USER)
		theirs = self._new("Administrator")  # owner not a branch peer, no warehouse
		self.assertTrue(mine.name.startswith("KSEPI-"), mine.name)
		self.assertEqual(cint(mine.update_stock), 0)
		with _as_user(BRANCH_USER):
			visible = frappe.get_list(
				"Purchase Invoice",
				filters={"custom_is_expense_invoice": 1, "name": ["in", [mine.name, theirs.name]]},
				pluck="name",
			)
		self.assertEqual(visible, [mine.name])


class TestRow33Print(FrappeTestCase):
	def _expense(self):
		name = frappe.db.get_value("Purchase Invoice", {"docstatus": 1, "custom_is_expense_invoice": 1}, "name")
		if not name:
			self.skipTest("no submitted expense invoice")
		doc = frappe.get_doc("Purchase Invoice", name)
		doc.select_print_heading = ""
		return doc

	def test_a_flagged_invoice_defaults_to_the_expenses_heading(self):
		from yht_custom import print_heading

		doc = frappe._dict(doctype="Purchase Invoice", custom_is_expense_invoice=1, is_return=0)
		self.assertEqual(print_heading.default_heading(doc), "Expenses Invoice")

	def test_the_expense_format_reads_the_heading_behind_the_switch(self):
		fmt = json.loads(_source("yht_custom/print_format/yht_expense_invoice/yht_expense_invoice.json"))
		self.assertIn(f'yht_feature("{R33}")', fmt["html"])
		self.assertIn("yht_print_heading(doc)", fmt["html"])
		self.assertIn("{% else %}", fmt["html"])
		self.assertGreater(fmt["modified"], "2026-08-20 14:55:00.000000")  # gotcha 23

	def test_on_the_page_reads_expenses_invoice_off_it_reads_expense_invoice(self):
		doc, html = self._expense(), _format_html("yht_expense_invoice")
		on = _render(doc, html).lower()
		with _off(R33):
			off = _render(doc, html).lower()
		self.assertIn("expenses invoice", on)
		self.assertIn("expense invoice", off)
		self.assertNotIn("expenses invoice", off)

	def test_the_purchase_invoice_format_is_byte_identical_on_and_off(self):
		doc, html = self._expense(), _format_html("yht_purchase_invoice")
		on = _render(doc, html)
		with _off(R33):
			off = _render(doc, html)
		self.assertEqual(hashlib.sha256(on.encode()).hexdigest(), hashlib.sha256(off.encode()).hexdigest())


class TestRow33Scripts(FrappeTestCase):
	def setUp(self):
		self.js = _source("public/js/expense_invoice.js")
		self.dash = _source("yht_custom/page/yht_dashboard/yht_dashboard.js")

	def test_new_expense_opens_a_purchase_invoice_with_the_flag_through_route_options(self):
		self.assertIn("yht_custom.expense.new_expense", self.js)
		self.assertIn('frappe.new_doc("Purchase Invoice", {custom_is_expense_invoice: 1})', self.js)

	def test_the_new_form_is_pre_numbered_with_the_expense_series_only_when_it_is_offered(self):
		self.assertIn("KSEPI-.YY.-.####", self.js)
		self.assertIn("frm.is_new()", self.js)
		self.assertIn("is_return", self.js)
		self.assertRegex(self.js, r"options[^;]{0,120}(includes|indexOf)")

	def test_the_printer_icon_preselects_the_expense_format_and_restores_the_original(self):
		self.assertIn("frm.meta.default_print_format", self.js)
		self.assertIn("__yht_pf", self.js)
		self.assertIn("YHT Expense Invoice", self.js)
		self.assertIn(R33, self.js)

	def test_the_dashboard_carries_both_tiles_behind_the_switch(self):
		self.assertEqual(self.dash.count(f'feature: "{R33}"'), 2)
		for label in ("Record Expense", "Expense Invoices"):
			self.assertIn(f'label: "{label}"', self.dash)
		self.assertIn("data-yht-expense", self.dash)
		self.assertIn("yht_custom.expense.new_expense", self.dash)
		self.assertRegex(self.dash, r"custom_is_expense_invoice\s*:\s*1")

	def test_the_dashboard_tile_destination_is_in_the_allow_list(self):
		self.assertIn('"Purchase Invoice"', _source("public/js/branch_user_restrict.js"))


# ======================================================================= row 35


def _python_files():
	for path in sorted(ROOT.rglob("*.py")):
		if "tests" in path.parts:
			continue
		yield path


def _walk(path):
	"""(function, node, enclosing-source) for every Call and Constant in a module."""
	source = path.read_text()
	tree = ast.parse(source)
	out = []

	class Visitor(ast.NodeVisitor):
		def __init__(self):
			self.stack = []

		def visit_FunctionDef(self, node):
			self.stack.append(node)
			self.generic_visit(node)
			self.stack.pop()

		visit_AsyncFunctionDef = visit_FunctionDef

		def visit(self, node):
			if isinstance(node, (ast.Call, ast.Constant)):
				fn = self.stack[-1] if self.stack else None
				out.append((fn.name if fn else None, node, ast.get_source_segment(source, fn) if fn else ""))
			super().visit(node)

	Visitor().visit(tree)
	return out


class TestRow35StaticGuard(FrappeTestCase):
	"""CHARACTERISATION — green today, and the guard that must stay green."""

	def test_default_print_format_is_only_written_where_it_is_allowed(self):
		offenders = []
		for path in _python_files():
			hits = [(fn, src) for fn, node, src in _walk(path)
			        if isinstance(node, ast.Constant) and node.value == "default_print_format"]
			if not hits:
				continue
			if path.name == "print_consolidation.py":
				continue  # reads / deletes stale setters only
			if path.name == "setup.py":
				for fn, src in hits:
					# the DocType-row write — a Property Setter would override the client's own
					if fn != "setup_default_print_formats" or 'set_value("DocType"' not in src or "Property Setter" in src:
						offenders.append(f"{path}:{fn}")
				continue
			offenders.append(str(path.relative_to(ROOT)))
		self.assertEqual(offenders, [], "a new writer of default_print_format needs an explicit decision")

	def test_print_format_records_are_only_written_by_the_three_known_functions(self):
		allowed = {
			("print_consolidation.py", "setup_print_consolidation"),   # disables names in SUPERSEDED
			("print_consolidation.py", "restore"),                      # re-enables them
			("setup.py", "setup_sales_invoice_qr"),                     # re-points Sales Invoice Print's module
		}
		writers = set()
		for path in _python_files():
			for fn, node, src in _walk(path):
				if not isinstance(node, ast.Call):
					continue
				name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
				first = node.args[0] if node.args else None
				first_is_pf = isinstance(first, ast.Constant) and first.value == "Print Format"
				dict_pf = isinstance(first, ast.Dict) and any(
					isinstance(k, ast.Constant) and k.value == "doctype"
					and isinstance(v, ast.Constant) and v.value == "Print Format"
					for k, v in zip(first.keys, first.values)
				)
				if name in ("set_value", "delete_doc", "db_set_value") and first_is_pf:
					writers.add((path.name, fn))
				elif name == "get_doc" and (first_is_pf and ".save(" in src or dict_pf):
					writers.add((path.name, fn))
		self.assertLessEqual(writers, allowed, writers - allowed)


class TestRow35TheClientsFormatsAreNeverTouched(FrappeTestCase):
	DOCTYPES = ("Sales Invoice", "Quotation", "Purchase Order", "Delivery Note")

	def _snapshot(self):
		setters = sorted(
			(r.doc_type, r.value)
			for r in frappe.get_all("Property Setter", filters={"property": "default_print_format"},
			                        fields=["doc_type", "value"])
		)
		formats = sorted(
			(r.name, r.disabled, hashlib.md5((r.html or "").encode()).hexdigest(), str(r.modified))
			for r in frappe.get_all("Print Format", filters={"standard": "No"},
			                        fields=["name", "disabled", "html", "modified"])
		)
		return setters, formats

	def test_running_the_consolidation_and_the_default_writer_changes_none_of_it(self):
		from yht_custom import print_consolidation as pc
		from yht_custom import setup

		for doctype, name in zip(self.DOCTYPES, ("_T-R35-A", "_T-R35-B", "_T-R35-C", "_T-R35-D")):
			_setter(doctype, _format(name, doctype), "saheed@kathoomcompany.com")
		frappe.clear_cache()
		before = self._snapshot()
		effective = {d: frappe.get_meta(d).default_print_format for d in self.DOCTYPES}
		pc.setup_print_consolidation()
		setup.setup_default_print_formats()
		frappe.clear_cache()
		self.assertEqual(before, self._snapshot())
		self.assertEqual(effective, {d: frappe.get_meta(d).default_print_format for d in self.DOCTYPES})

	def test_a_client_built_format_that_shares_a_retired_name_is_not_disabled(self):
		from yht_custom import print_consolidation as pc

		_format("_T-R35-CLIENT", "Quotation")
		self.assertEqual(frappe.db.get_value("Print Format", "_T-R35-CLIENT", "disabled"), 0)
		with mock.patch.object(pc, "SUPERSEDED", {"_T-R35-CLIENT": "x"}):
			pc.setup_print_consolidation()
		self.assertEqual(frappe.db.get_value("Print Format", "_T-R35-CLIENT", "disabled"), 0)

	def test_restore_never_re_enables_a_client_built_format(self):
		from yht_custom import print_consolidation as pc

		_format("_T-R35-CLIENT-OFF", "Quotation")
		frappe.db.set_value("Print Format", "_T-R35-CLIENT-OFF", "disabled", 1, update_modified=False)
		with mock.patch.object(frappe.db, "commit"):  # `restore` commits; a test must not (gotcha 74)
			result = pc.restore(["_T-R35-CLIENT-OFF"])
		self.assertEqual(frappe.db.get_value("Print Format", "_T-R35-CLIENT-OFF", "disabled"), 1)
		self.assertNotIn("_T-R35-CLIENT-OFF", result["restored"])

	def test_our_own_retired_formats_are_still_retired_and_restorable(self):
		"""The hardening is a pure restriction: `standard = Yes` names behave as before."""
		from yht_custom import print_consolidation as pc

		ours = [n for n in pc.SUPERSEDED if frappe.db.get_value("Print Format", n, "standard") == "Yes"]
		if not ours:
			self.skipTest("no standard SUPERSEDED format on this site")
		pc.setup_print_consolidation()
		for name in ours:
			self.assertEqual(frappe.db.get_value("Print Format", name, "disabled"), 1, name)

	def test_the_clients_four_are_still_declared_verbatim(self):
		from yht_custom import print_consolidation as pc

		self.assertEqual(
			pc.CLIENT_DEFAULT_PRINT_FORMATS,
			{"Sales Invoice": "SALES-INVOICE", "Quotation": "SALES-QUOTATION",
			 "Purchase Order": "PURCHASE-ORDER", "Delivery Note": "DELIVERY-NOTE W/O HEAD"},
		)

	def test_the_delivery_note_alternative_is_declared(self):
		from yht_custom import print_consolidation as pc

		self.assertEqual(pc.CLIENT_DEFAULT_ALTERNATIVES, {"Delivery Note": ("DELIVERY-NOTE W HEAD",)})


class TestRow35CheckClientDefaults(FrappeTestCase):
	def _check(self):
		from yht_custom import print_consolidation as pc

		return pc.check_client_defaults()["Delivery Note"]

	def _with_default(self, value):
		_setter("Delivery Note", value, "saheed@kathoomcompany.com")
		frappe.clear_cache(doctype="Delivery Note")

	def test_the_w_head_format_is_accepted(self):
		self._with_default(_format("DELIVERY-NOTE W HEAD", "Delivery Note"))
		self.assertEqual(self._check()["status"], "OK")

	def test_the_w_o_head_format_is_accepted(self):
		self._with_default(_format("DELIVERY-NOTE W/O HEAD", "Delivery Note"))
		self.assertEqual(self._check()["status"], "OK")

	def test_a_disabled_default_is_a_fail_with_a_reason(self):
		name = _format("_T-R35-DISABLED", "Delivery Note")
		frappe.db.set_value("Print Format", name, "disabled", 1, update_modified=False)
		self._with_default(name)
		row = self._check()
		self.assertEqual(row["status"], "FAIL")
		self.assertTrue(row.get("reason"))

	def test_a_default_naming_a_format_that_does_not_exist_is_a_fail(self):
		self._with_default("_T-R35-NO-SUCH-FORMAT")
		row = self._check()
		self.assertEqual(row["status"], "FAIL")
		self.assertTrue(row.get("reason"))

	def test_an_enabled_app_format_with_no_client_format_on_the_site_is_a_skip(self):
		if any(frappe.db.exists("Print Format", n) for n in ("DELIVERY-NOTE W HEAD", "DELIVERY-NOTE W/O HEAD")):
			self.skipTest("this site carries one of the client's Delivery Note formats")
		self._with_default(_one_of_ours())
		self.assertTrue(self._check()["status"].startswith("SKIP"))

	def test_a_default_that_is_neither_accepted_name_is_a_fail_once_one_exists(self):
		_format("DELIVERY-NOTE W HEAD", "Delivery Note")
		self._with_default(_one_of_ours())
		self.assertEqual(self._check()["status"], "FAIL")

	def test_ok_fail_and_skip_stay_three_distinct_outcomes(self):
		"""Gotcha 31/119: an ERROR or a SKIP is never a pass."""
		from yht_custom import print_consolidation as pc

		ok = _format("DELIVERY-NOTE W HEAD", "Delivery Note")
		self._with_default(ok)
		status_ok = self._check()["status"]
		self._with_default("_T-R35-NO-SUCH-FORMAT")
		status_fail = self._check()["status"]
		self.assertEqual((status_ok, status_fail), ("OK", "FAIL"))
		rows = pc.check_client_defaults()
		for doctype in pc.CLIENT_DEFAULT_PRINT_FORMATS:
			self.assertIn("status", rows[doctype])  # the existing three-outcome assertion keeps passing
