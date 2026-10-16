# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Meeting of 2026-10-15 — rows 40, 42, 43, 45, 46, 48.

Runs on `yht-test` only (`yht_features` is `["all"]` there):

    bench --site yht-test run-tests --app yht_custom --skip-before-tests \
        --module yht_custom.tests.test_meeting_1015

Nothing commits (gotcha 74). The browser behaviour of rows 40 / 45 / 48 is checked separately by
`scripts/ui_check_1015.py` against the real desk; the source tests here only pin the contract.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import connected_documents as cd
from yht_custom import features, meeting_1011, meeting_1015
from yht_custom.tests.test_meeting_1011_wednesday import _fieldnames, _off, _source

SWITCHES = (
	"oct15_r40_pe_account_lock",
	"oct15_r42_quotation_sales_team",
	"oct15_r43_opportunity_bulk_items",
	"oct15_r45_add_multiple_sort",
	"oct15_r46_connected_numbers",
	"oct15_r48_print_pdf_default",
)


class TestSwitches(FrappeTestCase):
	def test_every_switch_is_known(self):
		for name in SWITCHES:
			with self.subTest(switch=name):
				self.assertIn(name, features.KNOWN)
				features.enabled(name)  # must not raise


class TestRow43OpportunityBulkItems(FrappeTestCase):
	def test_the_items_grid_gets_download_and_upload(self):
		meeting_1015.setup_opportunity_bulk_items()
		frappe.clear_cache(doctype="Opportunity")
		self.assertEqual(frappe.get_meta("Opportunity", cached=False).get_field("items").allow_bulk_edit, 1)

	def test_it_matches_quotation(self):
		self.assertEqual(frappe.get_meta("Quotation").get_field("items").allow_bulk_edit, 1)

	def test_it_waits_for_its_switch(self):
		with _off("oct15_r43_opportunity_bulk_items"):
			self.assertIn("skipped", meeting_1015.setup_opportunity_bulk_items())


class TestRow42QuotationSalesTeam(FrappeTestCase):
	def setUp(self):
		meeting_1015.setup_quotation_sales_team()
		frappe.clear_cache(doctype="Quotation")

	def _a_customer_with_a_team(self):
		name = frappe.db.sql(
			"SELECT parent FROM `tabSales Team` WHERE parenttype = 'Customer' LIMIT 1", pluck=True
		)
		if not name:
			self.skipTest("no customer with a sales team on this site")
		return name[0]

	def test_quotation_has_the_table(self):
		field = frappe.get_meta("Quotation", cached=False).get_field("sales_team")
		self.assertIsNotNone(field)
		self.assertEqual((field.fieldtype, field.options), ("Table", "Sales Team"))

	def test_it_is_idempotent(self):
		again = meeting_1015.setup_quotation_sales_team()
		self.assertIn("adopted", again)

	def test_the_team_is_copied_from_the_customer(self):
		customer = self._a_customer_with_a_team()
		doc = frappe.new_doc("Quotation")
		doc.quotation_to, doc.party_name = "Customer", customer
		cd.fill_quotation_sales_team(doc)
		expected = frappe.get_all(
			"Sales Team", filters={"parenttype": "Customer", "parent": customer}, pluck="sales_person", order_by="idx asc"
		)
		self.assertEqual([r.sales_person for r in doc.sales_team], expected)
		self.assertEqual(sum(r.allocated_percentage or 0 for r in doc.sales_team), 100)

	def test_an_existing_team_is_never_touched(self):
		customer = self._a_customer_with_a_team()
		doc = frappe.new_doc("Quotation")
		doc.quotation_to, doc.party_name = "Customer", customer
		doc.append("sales_team", {"sales_person": "Sales Team", "allocated_percentage": 100})
		cd.fill_quotation_sales_team(doc)
		self.assertEqual([r.sales_person for r in doc.sales_team], ["Sales Team"])

	def test_a_lead_quotation_gets_nothing(self):
		doc = frappe.new_doc("Quotation")
		doc.quotation_to, doc.party_name = "Lead", "x"
		cd.fill_quotation_sales_team(doc)
		self.assertFalse(doc.get("sales_team"))

	def test_the_handler_waits_for_its_switch(self):
		customer = self._a_customer_with_a_team()
		doc = frappe.new_doc("Quotation")
		doc.quotation_to, doc.party_name = "Customer", customer
		with _off("oct15_r42_quotation_sales_team"):
			cd.fill_quotation_sales_team(doc)
		self.assertFalse(doc.get("sales_team"))

	def test_the_print_helper_now_finds_the_team_on_the_document(self):
		from yht_custom.print_helpers import yht_sales_person

		customer = self._a_customer_with_a_team()
		doc = frappe.new_doc("Quotation")
		doc.quotation_to, doc.party_name = "Customer", customer
		cd.fill_quotation_sales_team(doc)
		self.assertEqual(yht_sales_person(doc)["name"], doc.sales_team[0].sales_person)

	def test_the_provisioning_runs_before_the_front_block(self):
		from yht_custom import setup

		steps = list(setup.PROVISIONING_STEPS)
		self.assertLess(steps.index("setup_quotation_sales_team"), steps.index("setup_front_details"))


class TestRow46ConnectedNumbers(FrappeTestCase):
	def setUp(self):
		meeting_1015.setup_connected_numbers()
		for dt in ("Sales Invoice", "Sales Order"):
			frappe.clear_cache(doctype=dt)

	def test_the_fields_exist_on_the_front_page(self):
		for doctype, fields in cd.CUSTOM_FIELDS.items():
			order = _fieldnames(doctype)
			boundary = meeting_1011._front_boundary(order)
			for name, _label in fields:
				with self.subTest(doctype=doctype, field=name):
					self.assertIn(name, order)
					self.assertLess(order.index(name), boundary)

	def test_it_is_a_permutation_and_idempotent(self):
		before = {dt: sorted(_fieldnames(dt)) for dt in cd.CUSTOM_FIELDS}
		meeting_1015.setup_connected_numbers()
		for dt in cd.CUSTOM_FIELDS:
			self.assertEqual(sorted(_fieldnames(dt)), before[dt])

	def test_the_fields_are_read_only_and_allowed_after_submit(self):
		for doctype, fields in cd.CUSTOM_FIELDS.items():
			for name, _label in fields:
				df = frappe.get_meta(doctype).get_field(name)
				self.assertEqual((df.read_only, df.allow_on_submit), (1, 1), f"{doctype}.{name}")

	def _an_order_with_a_note(self):
		rows = frappe.db.sql(
			"""SELECT i.against_sales_order FROM `tabDelivery Note Item` i
			INNER JOIN `tabDelivery Note` dn ON dn.name = i.parent
			WHERE dn.docstatus = 1 AND dn.is_return = 0 AND IFNULL(i.against_sales_order, '') != '' LIMIT 1""",
			pluck=True,
		)
		if not rows:
			self.skipTest("no delivered Sales Order on this site")
		return rows[0]

	def test_an_order_lists_its_submitted_notes(self):
		order = self._an_order_with_a_note()
		cd.refresh_order(order)
		got = frappe.db.get_value("Sales Order", order, "custom_delivery_note_no") or ""
		expected = cd._joined(cd._notes_of_order(order))
		self.assertEqual(got, expected)
		self.assertTrue(got)

	def test_an_order_lists_its_submitted_invoices(self):
		rows = frappe.db.sql(
			"""SELECT i.sales_order FROM `tabSales Invoice Item` i INNER JOIN `tabSales Invoice` si ON si.name = i.parent
			WHERE si.docstatus = 1 AND si.is_return = 0 AND IFNULL(i.sales_order, '') != '' LIMIT 1""",
			pluck=True,
		)
		if not rows:
			self.skipTest("no invoiced Sales Order on this site")
		cd.refresh_order(rows[0])
		self.assertEqual(
			frappe.db.get_value("Sales Order", rows[0], "custom_sales_invoice_no") or "",
			cd._joined(cd._invoices_of_order(rows[0])),
		)

	def test_a_write_does_not_touch_modified(self):
		order = self._an_order_with_a_note()
		frappe.db.set_value("Sales Order", order, "custom_delivery_note_no", "", update_modified=False)
		before = frappe.db.get_value("Sales Order", order, "modified")
		cd.refresh_order(order)
		self.assertEqual(frappe.db.get_value("Sales Order", order, "modified"), before)

	def test_an_invoice_reads_its_own_rows_at_validate(self):
		doc = frappe.new_doc("Sales Invoice")
		doc.append("items", {"sales_order": "SO-A", "delivery_note": "DN-A"})
		doc.append("items", {"sales_order": "SO-B", "delivery_note": "DN-A"})
		cd.set_invoice_numbers(doc)
		self.assertEqual(doc.custom_sales_order_no, "SO-A, SO-B")
		self.assertEqual(doc.custom_delivery_note_no, "DN-A")

	def test_the_handlers_wait_for_their_switch(self):
		doc = frappe.new_doc("Sales Invoice")
		doc.append("items", {"sales_order": "SO-A"})
		with _off("oct15_r46_connected_numbers"):
			cd.set_invoice_numbers(doc)
		self.assertFalse(doc.get("custom_sales_order_no"))

	def test_the_handlers_are_registered(self):
		events = frappe.get_hooks("doc_events", app_name="yht_custom")
		for doctype, event, path in (
			("Sales Invoice", "validate", "yht_custom.connected_documents.set_invoice_numbers"),
			("Sales Invoice", "on_submit", "yht_custom.connected_documents.after_invoice"),
			("Delivery Note", "on_cancel", "yht_custom.connected_documents.after_note"),
			("Quotation", "before_validate", "yht_custom.connected_documents.fill_quotation_sales_team"),
		):
			with self.subTest(doctype=doctype, event=event):
				handlers = events.get(doctype, {}).get(event)
				handlers = handlers if isinstance(handlers, list) else [handlers]
				self.assertIn(path, handlers)

	def test_the_backfill_dry_run_reports_and_writes_nothing(self):
		with _quiet():
			summary = cd.backfill(commit=False)
		self.assertFalse(summary["committed"])
		self.assertTrue(summary["updated"])
		self.assertTrue(all(v == 0 for v in summary["updated"].values()), summary["updated"])


class TestRow46WholeChain(FrappeTestCase):
	"""2026-10-16 — "for ALL invoice types: if any is connected with any other, show the number"."""

	def setUp(self):
		meeting_1015.setup_connected_numbers()
		for dt in cd.CUSTOM_FIELDS:
			frappe.clear_cache(doctype=dt)

	def test_every_document_of_the_chain_has_its_fields_on_the_front_page(self):
		self.assertEqual(
			set(cd.CUSTOM_FIELDS),
			{"Quotation", "Sales Order", "Sales Invoice", "Purchase Order", "Purchase Receipt", "Purchase Invoice"},
		)
		for doctype, fields in cd.CUSTOM_FIELDS.items():
			order = _fieldnames(doctype)
			boundary = meeting_1011._front_boundary(order)
			for name, _label in fields:
				with self.subTest(doctype=doctype, field=name):
					self.assertIn(name, order)
					self.assertLess(order.index(name), boundary)

	def test_the_maps_only_name_fields_that_exist(self):
		for doctype, spec in cd.OWN_ROWS.items():
			child = frappe.get_meta(doctype).get_field("items").options
			for fieldname, row_field in spec.items():
				self.assertTrue(frappe.get_meta(doctype).has_field(fieldname), f"{doctype}.{fieldname}")
				self.assertTrue(frappe.get_meta(child).has_field(row_field), f"{child}.{row_field}")
		for doctype, spec in cd.BY_OTHERS.items():
			for fieldname, (other, child, row_field) in spec.items():
				self.assertTrue(frappe.get_meta(doctype).has_field(fieldname), f"{doctype}.{fieldname}")
				self.assertTrue(frappe.get_meta(child).has_field(row_field), f"{child}.{row_field}")

	def _first(self, sql, *args):
		rows = frappe.db.sql(sql, args, pluck=True)
		if not rows:
			self.skipTest("no such linked document on this site")
		return rows[0]

	def test_a_purchase_order_lists_its_receipts_and_invoices(self):
		name = self._first(
			"""SELECT i.purchase_order FROM `tabPurchase Invoice Item` i INNER JOIN `tabPurchase Invoice` d ON d.name = i.parent
			WHERE d.docstatus = 1 AND d.is_return = 0 AND IFNULL(i.purchase_order, '') != '' LIMIT 1"""
		)
		cd.refresh_by_others("Purchase Order", name)
		got = frappe.db.get_value("Purchase Order", name, ["custom_purchase_receipt_no", "custom_purchase_invoice_no"], as_dict=True)
		self.assertEqual(
			got.custom_purchase_invoice_no or "",
			cd._joined(cd._names_pointing_at("Purchase Invoice", "Purchase Invoice Item", "purchase_order", name)),
		)
		self.assertTrue(got.custom_purchase_invoice_no)

	def test_returns_are_never_listed(self):
		name = self._first(
			"""SELECT i.purchase_order FROM `tabPurchase Receipt Item` i INNER JOIN `tabPurchase Receipt` d ON d.name = i.parent
			WHERE d.docstatus = 1 AND d.is_return = 1 AND IFNULL(i.purchase_order, '') != '' LIMIT 1"""
		)
		cd.refresh_by_others("Purchase Order", name)
		listed = (frappe.db.get_value("Purchase Order", name, "custom_purchase_receipt_no") or "").split(", ")
		returns = frappe.get_all("Purchase Receipt", filters={"is_return": 1, "name": ["in", [x for x in listed if x]]}, pluck="name")
		self.assertEqual(returns, [])

	def test_a_purchase_receipt_lists_its_invoices_and_reads_its_order(self):
		name = self._first(
			"""SELECT i.purchase_receipt FROM `tabPurchase Invoice Item` i INNER JOIN `tabPurchase Invoice` d ON d.name = i.parent
			WHERE d.docstatus = 1 AND d.is_return = 0 AND IFNULL(i.purchase_receipt, '') != '' LIMIT 1"""
		)
		cd.refresh_by_others("Purchase Receipt", name)
		self.assertTrue(frappe.db.get_value("Purchase Receipt", name, "custom_purchase_invoice_no"))
		cd.refresh_own("Purchase Receipt", name)
		order = frappe.db.sql(
			"SELECT DISTINCT purchase_order FROM `tabPurchase Receipt Item` WHERE parent = %s AND IFNULL(purchase_order, '') != ''",
			(name,),
			pluck=True,
		)
		self.assertEqual(frappe.db.get_value("Purchase Receipt", name, "custom_purchase_order_no") or "", cd._joined(order))

	def test_a_quotation_lists_the_orders_made_from_it(self):
		name = self._first(
			"""SELECT i.prevdoc_docname FROM `tabSales Order Item` i INNER JOIN `tabSales Order` d ON d.name = i.parent
			WHERE d.docstatus = 1 AND IFNULL(i.prevdoc_docname, '') != '' LIMIT 1"""
		)
		cd.refresh_by_others("Quotation", name)
		self.assertEqual(
			frappe.db.get_value("Quotation", name, "custom_sales_order_no") or "",
			cd._joined(cd._names_pointing_at("Sales Order", "Sales Order Item", "prevdoc_docname", name)),
		)

	def test_a_purchase_invoice_reads_its_own_rows_at_validate(self):
		doc = frappe.new_doc("Purchase Invoice")
		doc.append("items", {"purchase_order": "PO-A", "purchase_receipt": "PR-A"})
		doc.append("items", {"purchase_order": "PO-A", "purchase_receipt": "PR-B"})
		cd.set_own_numbers(doc)
		self.assertEqual(doc.custom_purchase_order_no, "PO-A")
		self.assertEqual(doc.custom_purchase_receipt_no, "PR-A, PR-B")

	def test_a_sales_order_reads_its_quotation_at_validate(self):
		doc = frappe.new_doc("Sales Order")
		doc.append("items", {"prevdoc_docname": "SAL-QTN-1"})
		cd.set_own_numbers(doc)
		self.assertEqual(doc.custom_quotation_no, "SAL-QTN-1")

	def test_the_handlers_are_registered_for_the_rest_of_the_chain(self):
		events = frappe.get_hooks("doc_events", app_name="yht_custom")
		for doctype in ("Sales Order", "Purchase Receipt", "Purchase Invoice"):
			for event, path in (
				("validate", "yht_custom.connected_documents.set_own_numbers"),
				("on_submit", "yht_custom.connected_documents.after_document"),
				("on_cancel", "yht_custom.connected_documents.after_document"),
			):
				with self.subTest(doctype=doctype, event=event):
					handlers = events.get(doctype, {}).get(event)
					handlers = handlers if isinstance(handlers, list) else [handlers]
					self.assertIn(path, handlers)

	def test_the_handlers_wait_for_their_switch(self):
		doc = frappe.new_doc("Purchase Invoice")
		doc.append("items", {"purchase_order": "PO-A"})
		with _off("oct15_r46_connected_numbers"):
			cd.set_own_numbers(doc)
		self.assertFalse(doc.get("custom_purchase_order_no"))

	def test_a_name_that_is_not_in_the_maps_cannot_reach_the_query(self):
		with self.assertRaises(AssertionError):
			cd._names_pointing_at("User", "Has Role", "role", "x")


class TestJavaScriptContracts(FrappeTestCase):
	def test_row_45_rewrites_the_query_in_link_search_behind_both_switches(self):
		js = _source("public/js/item_search.js")
		self.assertIn("frappe.link_search = link_search", js)
		self.assertIn("oct15_r45_add_multiple_sort", js)
		self.assertIn("oct08_r07_item_search", js)
		self.assertIn("/assets/yht_custom/js/item_search.js?v=2", _source("hooks.py"))

	def test_row_48_resolves_the_format_from_the_meta_default_behind_its_switch(self):
		js = _source("public/js/katc_print_buttons.js")
		self.assertIn("oct15_r48_print_pdf_default", js)
		self.assertIn("frm.meta.default_print_format", js)
		self.assertIn("spec = katc_resolved_spec(frm, spec);", js)
		# the KATC letterhead record and the "en" pin must not follow a client-built format
		self.assertIn("if (!katc_is_ours(chosen)) delete out.letterhead;", js)
		self.assertIn("if (!katc_is_ours(spec.format)) delete args.language;", js)

	def test_row_40_is_registered_with_a_version_and_gated(self):
		self.assertIn("/assets/yht_custom/js/payment_entry_accounts.js?v=1", _source("hooks.py"))
		js = _source("public/js/payment_entry_accounts.js")
		self.assertIn("oct15_r40_pe_account_lock", js)
		self.assertIn("set_company_bank_account", js)
		self.assertIn('frappe.model.can_read("Bank Account")', js)
		for field in ("paid_from", "paid_to", "mode_of_payment", "payment_type"):
			self.assertIn(field, js)


import contextlib
import io


@contextlib.contextmanager
def _quiet():
	with contextlib.redirect_stdout(io.StringIO()):
		yield


class TestRow46ConnectedTable(FrappeTestCase):
	"""2026-10-16 — "a table on the right side, click a number to open the document"."""

	def setUp(self):
		meeting_1015.setup_connected_numbers()
		for dt in cd.TABLE_ANCHORS:
			frappe.clear_cache(doctype=dt)

	def test_one_html_field_per_document_on_the_front_page(self):
		self.assertEqual(set(cd.TABLE_ANCHORS), set(cd.CUSTOM_FIELDS))
		for doctype in cd.TABLE_ANCHORS:
			with self.subTest(doctype=doctype):
				order = _fieldnames(doctype)
				self.assertIn(cd.TABLE_FIELD, order)
				self.assertEqual(frappe.get_meta(doctype).get_field(cd.TABLE_FIELD).fieldtype, "HTML")
				self.assertLess(order.index(cd.TABLE_FIELD), meeting_1011._front_boundary(order))

	def test_the_numbers_stay_as_fields_but_leave_the_form(self):
		for doctype, fields in cd.CUSTOM_FIELDS.items():
			for name, _label in fields:
				df = frappe.get_meta(doctype).get_field(name)
				with self.subTest(doctype=doctype, field=name):
					self.assertEqual(df.depends_on, "eval:0")
					self.assertEqual(df.hidden, 0)  # hidden would drop it from the list-view column picker

	def test_the_long_hints_are_short(self):
		for doctype in cd.TABLE_ANCHORS:
			for name in ("custom_fiscal_year", "custom_other_remarks"):
				df = frappe.get_meta(doctype).get_field(name)
				if df:
					with self.subTest(doctype=doctype, field=name):
						self.assertLess(len(df.description or ""), 90)

	def test_it_is_idempotent(self):
		before = {dt: _fieldnames(dt) for dt in cd.TABLE_ANCHORS}
		again = meeting_1015.setup_connected_numbers()["table"]
		self.assertEqual((again["placed"], again["hidden"], again["hints"]), ([], [], []))
		for dt in cd.TABLE_ANCHORS:
			self.assertEqual(_fieldnames(dt), before[dt])

	def test_the_script_covers_exactly_the_stored_fields(self):
		import re

		from yht_custom import hooks

		source = _source("public/js/connected_documents.js")
		for doctype, fields in cd.CUSTOM_FIELDS.items():
			with self.subTest(doctype=doctype):
				self.assertIn("public/js/connected_documents.js", hooks.doctype_js[doctype])
				block = re.search(r'"%s": \[(.*?)\n\t\t?\],?\n' % doctype, source, re.S)
				self.assertTrue(block, f"{doctype} missing from the script's map")
				for name, _label in fields:
					self.assertIn(name, block.group(1))

	def test_the_quotation_team_is_on_the_front_page(self):
		meeting_1015.setup_quotation_sales_team()
		from yht_custom.meeting_1011_wednesday import setup_front_details

		setup_front_details()
		frappe.clear_cache(doctype="Quotation")
		order = _fieldnames("Quotation")
		boundary = meeting_1011._front_boundary(order)
		self.assertLess(order.index("sales_team"), boundary)
		self.assertLess(order.index("custom_front_team_section"), order.index("sales_team"))
