# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Client sheet (Kathoom Alkhobar) — batch 3: items 24, 25, 27, 28, 29, 32, 33, 35, 36.

Written BEFORE the implementation. Every test in this file is expected to fail on
a bench that has not run the batch-3 change yet; that is the point.

Run:

    bench --site yht-test run-tests --app yht_custom --skip-before-tests

`--skip-before-tests` is not optional. Without it the runner's before_tests hook
runs erpnext's setup wizard against the site and DELETES Item Price rows — it cost
4,847 client rows once already.

Three standing rules this file obeys:

* **Never commit inside a test.** `FrappeTestCase` rolls back once per CLASS, not
  per test, so anything shared is restored in a `finally` as well.
* **`__global_search` is MyISAM.** `frappe.db.rollback()` cannot undo a write to
  it, so item 27's fixture deletes its own rows in a `finally` regardless.
* **Assert through the hook, not through the constant.** A test that reads the
  configuration back out of the module it came from proves only that the module
  imports.

Item 36 follows **Gate Decision Q9**, which OVERRIDES the spec body: the cheap
option ships — `in_standard_filter = 1` on the EXISTING `is_return` Check — and
the `custom_document_kind` Select, its hook and its backfill patch are DROPPED.
Several tests here assert that the withdrawn design is *absent*, because a coder
reading the spec body alone would build it.
"""

import importlib
import inspect
import json
import os
import re
import unittest
import uuid

import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, cint, cstr, flt, getdate, today

from yht_custom import boot, fiscal_year, form_layout, sales_flow, setup

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BRANCH = "_Test YHT Batch3 Branch"
BRANCH_USER = "_test_yht_batch3_user@example.invalid"
MANAGER_USER = "_test_yht_batch3_manager@example.invalid"


# --------------------------------------------------------------------- helpers


def _module(name):
	"""Import a module this batch creates, failing ONE test rather than the file.

	A module-level `from yht_custom import delivery_backlink` aborts collection of
	the whole file the moment any one of the five new modules is missing, and every
	other item's result vanishes with it. That is exactly the "one failure hides
	another" shape `PROVISIONING_STEPS` was split up to avoid, so the tests are
	split the same way.
	"""
	try:
		return importlib.import_module(f"yht_custom.{name}")
	except ImportError as exc:  # pragma: no cover - TDD state
		raise AssertionError(f"yht_custom/{name}.py is not implemented yet ({exc})") from None


def _attr(module, name):
	value = getattr(module, name, None)
	if value is None:
		raise AssertionError(f"{module.__name__}.{name} is not implemented yet")
	return value


def _source(relative_path):
	path = os.path.join(APP_ROOT, relative_path)
	if not os.path.exists(path):
		raise AssertionError(f"{relative_path} does not exist yet")
	with open(path, encoding="utf-8") as handle:
		return handle.read()


def _first(doctype, filters=None, order_by=None):
	return frappe.db.get_value(doctype, filters or {}, "name", order_by=order_by)


def _property_setters(doctype, fieldname, prop):
	return frappe.get_all(
		"Property Setter",
		filters={"doc_type": doctype, "field_name": fieldname, "property": prop},
		fields=["name", "value", "doctype_or_field", "property_type"],
	)


def _doctype_property_setter(doctype, prop):
	rows = frappe.get_all(
		"Property Setter",
		filters={"doc_type": doctype, "property": prop},
		fields=["name", "value", "doctype_or_field", "field_name"],
	)
	return rows


def _count_queries(fn):
	"""Every SQL statement `fn` issues, in order.

	`frappe.qb(...).run()` funnels through `frappe.db.sql` too, so this catches the
	query-builder path as well as raw SQL. Used to prove item 25 asks ONE question
	about the rows rather than one per row.
	"""
	statements = []
	original = frappe.db.sql

	def spy(*args, **kwargs):
		statements.append(args[0] if args else kwargs.get("query"))
		return original(*args, **kwargs)

	frappe.db.sql = spy
	try:
		fn()
	finally:
		frappe.db.sql = original
	return statements


def _patch(module, name, value):
	"""Swap an attribute and hand back the restorer. Always used in a try/finally."""
	original = getattr(module, name)
	setattr(module, name, value)

	def restore():
		setattr(module, name, original)

	return restore


def _ensure_user(email, roles):
	if not frappe.db.exists("User", email):
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = email.split("@")[0]
		user.send_welcome_email = 0
		user.insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	have = {row.role for row in user.get("roles") or []}
	for role in roles:
		if role not in have and frappe.db.exists("Role", role):
			user.append("roles", {"role": role})
	user.save(ignore_permissions=True)
	frappe.clear_cache(user=email)
	return email


# ============================================================== item 24


class TestItem24TitleIsVoucherNumber(FrappeTestCase):
	"""The document title reads as the voucher number, on eight doctypes.

	The mechanism is a DocType-level `title_field = "name"` Property Setter, NOT a
	default on the `title` field. Two upstream facts make the alternative dead on
	arrival and both are asserted here, because a coder who reaches for the
	obvious `default` will otherwise ship something that looks configured and does
	nothing on three of the eight.
	"""

	def setUp(self):
		self.doctypes = getattr(form_layout, "TITLE_AS_VOUCHER_NO", None)
		if self.doctypes is None:
			self.fail("form_layout.TITLE_AS_VOUCHER_NO is not implemented yet")

	def tearDown(self):
		frappe.db.rollback()

	@unittest.skip(
		"The item 24 mechanism this asserts is WITHDRAWN. title_field = 'name' empties every transaction list (list_view.js resolves the subject column via frappe.meta.get_docfield and 'name' has no DocField). The step is unregistered, form_layout.setup_title_as_voucher_no throws, and patches.drop_title_as_voucher_no removes the rows. Re-point at whatever replacement is chosen - the client's own fallback is in_list_view = 0 on 'title'."
	)
	def test_the_map_covers_exactly_the_eight_doctypes_asked_for(self):
		self.assertEqual(
			set(self.doctypes),
			{
				"Sales Invoice",
				"Sales Order",
				"Delivery Note",
				"Quotation",
				"Purchase Invoice",
				"Purchase Receipt",
				"Payment Entry",
				"Journal Entry",
			},
		)

	@unittest.skip(
		"The item 24 mechanism this asserts is WITHDRAWN. title_field = 'name' empties every transaction list (list_view.js resolves the subject column via frappe.meta.get_docfield and 'name' has no DocField). The step is unregistered, form_layout.setup_title_as_voucher_no throws, and patches.drop_title_as_voucher_no removes the rows. Re-point at whatever replacement is chosen - the client's own fallback is in_list_view = 0 on 'title'."
	)
	def test_every_doctype_resolves_its_title_to_the_document_name(self):
		for doctype in self.doctypes:
			with self.subTest(doctype=doctype):
				self.assertEqual(frappe.get_meta(doctype).get_title_field(), "name")

	@unittest.skip(
		"The item 24 mechanism this asserts is WITHDRAWN. title_field = 'name' empties every transaction list (list_view.js resolves the subject column via frappe.meta.get_docfield and 'name' has no DocField). The step is unregistered, form_layout.setup_title_as_voucher_no throws, and patches.drop_title_as_voucher_no removes the rows. Re-point at whatever replacement is chosen - the client's own fallback is in_list_view = 0 on 'title'."
	)
	def test_the_property_setter_is_doctype_level(self):
		"""🔴 The `doctype_or_field` trap, again.

		`frappe.make_property_setter` defaults `doctype_or_field` to "DocField", and
		`Meta` only reads DOCTYPE-level rows for `title_field`. A DocField row
		inserts cleanly, the migrate reports success, and every title stays as it
		was. Twelve `sort_field` rows shipped that way once.
		"""
		for doctype in self.doctypes:
			with self.subTest(doctype=doctype):
				rows = [
					row
					for row in _doctype_property_setter(doctype, "title_field")
					if not row.get("field_name")
				]
				self.assertTrue(rows, f"{doctype}: no title_field Property Setter")
				self.assertEqual(rows[0]["doctype_or_field"], "DocType")
				self.assertEqual(rows[0]["value"], "name")

	@unittest.skip(
		"The item 24 mechanism this asserts is WITHDRAWN. title_field = 'name' empties every transaction list (list_view.js resolves the subject column via frappe.meta.get_docfield and 'name' has no DocField). The step is unregistered, form_layout.setup_title_as_voucher_no throws, and patches.drop_title_as_voucher_no removes the rows. Re-point at whatever replacement is chosen - the client's own fallback is in_list_view = 0 on 'title'."
	)
	def test_sales_order_overrides_a_shipped_title_field(self):
		"""Sales Order ships `title_field = "customer_name"`.

		This is the doctype that proves a `default` on the `title` FIELD could never
		have worked: `Document.set_title_field()` is guarded by
		`if self.meta.get("title_field") == "title"`, which is false here.
		"""
		self.assertEqual(frappe.get_meta("Sales Order").get_title_field(), "name")

	@staticmethod
	def _overrides_get_title(doc):
		"""Does this doctype's own controller replace `Document.get_title`?

		🔴 A CONTROLLER OVERRIDE BEATS EVERY PROPERTY SETTER, AND ONE DOCTYPE DOES IT.
		`frappe/model/document.py:553` resolves `get_title()` through
		`self.meta.get_title_field()`, which is exactly what this item sets — but
		`erpnext/accounts/doctype/journal_entry/journal_entry.py:249` REPLACES the
		method with `return self.pay_to_recd_from or self.accounts[0].account`, so
		no `title_field` row can change what Python returns for a Journal Entry
		(measured: `'HOUSSAM GULF TRADING EST.' != 'ACC-JV-2024-00001'`).

		The DESK HEADER is unaffected and is what the client asked for:
		`frappe/public/js/frappe/form/toolbar.js:48-50` renders
		`this.frm.doc[this.frm.meta.title_field] || this.frm.docname` — it reads the
		field, never `get_title()`, so with `title_field = "name"` the header shows
		the voucher number. Verified by opening a Journal Entry form on `yht-test`,
		not inferred: a green assertion over metadata is not a verified page.

		So the assertion splits by mechanism rather than dropping the doctype.
		"""
		return type(doc).get_title is not Document.get_title

	@unittest.skip(
		"The item 24 mechanism this asserts is WITHDRAWN. title_field = 'name' empties every transaction list (list_view.js resolves the subject column via frappe.meta.get_docfield and 'name' has no DocField). The step is unregistered, form_layout.setup_title_as_voucher_no throws, and patches.drop_title_as_voucher_no removes the rows. Re-point at whatever replacement is chosen - the client's own fallback is in_list_view = 0 on 'title'."
	)
	def test_an_existing_submitted_document_needs_no_backfill(self):
		"""Nothing is written to any row — the title is resolved at read time.

		Fetching a document created BEFORE the change and asking it for its title is
		the whole proof that no migration is required.
		"""
		checked = 0
		for doctype in self.doctypes:
			name = _first(doctype, {"docstatus": 1}, order_by="creation asc")
			if not name:
				continue
			checked += 1
			with self.subTest(doctype=doctype):
				doc = frappe.get_doc(doctype, name)
				self.assertEqual(doc.meta.get_title_field(), "name")
				if self._overrides_get_title(doc):
					continue  # see _overrides_get_title — the desk header still reads `name`
				self.assertEqual(doc.get_title(), name)
		if not checked:
			self.skipTest("no submitted documents on this site")

	@unittest.skip(
		"The item 24 mechanism this asserts is WITHDRAWN. title_field = 'name' empties every transaction list (list_view.js resolves the subject column via frappe.meta.get_docfield and 'name' has no DocField). The step is unregistered, form_layout.setup_title_as_voucher_no throws, and patches.drop_title_as_voucher_no removes the rows. Re-point at whatever replacement is chosen - the client's own fallback is in_list_view = 0 on 'title'."
	)
	def test_payment_entry_and_journal_entry_are_covered_despite_controller_titles(self):
		"""Both overwrite `title` from their controllers, so a field default is dead.

		`payment_entry.py::set_title()` and `journal_entry.py`'s
		`self.title = self.get_title()` run on every save. `title_field` is read
		instead of `title`, so the controller write becomes irrelevant rather than
		something to fight.

		Payment Entry only writes `self.title`, so `Document.get_title()` still
		resolves through `title_field` and returns the voucher number. Journal Entry
		goes one step further and overrides the METHOD — see `_overrides_get_title`
		for why that is asserted at the metadata level instead, and for the form
		check that backs it.
		"""
		for doctype in ("Payment Entry", "Journal Entry"):
			name = _first(doctype, {"docstatus": 1})
			if not name:
				continue
			with self.subTest(doctype=doctype):
				doc = frappe.get_doc(doctype, name)
				self.assertEqual(doc.meta.get_title_field(), "name")
				if self._overrides_get_title(doc):
					self.assertEqual(
						doctype, "Journal Entry", f"{doctype} grew a get_title override too"
					)
					continue
				self.assertEqual(doc.get_title(), doc.name)

	@unittest.skip(
		"The item 24 mechanism this asserts is WITHDRAWN. title_field = 'name' empties every transaction list (list_view.js resolves the subject column via frappe.meta.get_docfield and 'name' has no DocField). The step is unregistered, form_layout.setup_title_as_voucher_no throws, and patches.drop_title_as_voucher_no removes the rows. Re-point at whatever replacement is chosen - the client's own fallback is in_list_view = 0 on 'title'."
	)
	def test_the_sort_order_this_app_already_owns_was_not_clobbered(self):
		"""🔴 The collision the spec flags for the gate.

		`title_field`, `sort_field` and `sort_order` are all DOCTYPE-level, and a
		Customize Form save writes a Property Setter for EVERY doctype-level
		property the screen displays — not just the one that was changed. So a
		careless `setup_title_as_voucher_no` that rewrites the doctype's properties
		wholesale, rather than upserting the one row, silently reverts the
		`sort_field` rows `form_layout.SORT_BY_NAME` owns. Both must hold together.
		"""
		for doctype in form_layout.SORT_BY_NAME:
			if doctype not in self.doctypes:
				continue
			with self.subTest(doctype=doctype):
				meta = frappe.get_meta(doctype)
				self.assertEqual(meta.get_title_field(), "name")
				self.assertEqual(
					meta.sort_field, "name", f"{doctype}: setup_form_layout's sort_field was lost"
				)

	@unittest.skip(
		"The item 24 mechanism this asserts is WITHDRAWN. title_field = 'name' empties every transaction list (list_view.js resolves the subject column via frappe.meta.get_docfield and 'name' has no DocField). The step is unregistered, form_layout.setup_title_as_voucher_no throws, and patches.drop_title_as_voucher_no removes the rows. Re-point at whatever replacement is chosen - the client's own fallback is in_list_view = 0 on 'title'."
	)
	def test_running_the_step_twice_writes_nothing_new(self):
		step = _attr(form_layout, "setup_title_as_voucher_no")
		before = frappe.db.count("Property Setter")
		step()
		self.assertEqual(frappe.db.count("Property Setter"), before)

	def test_the_title_field_resolves_to_a_real_docfield_so_the_LIST_still_renders(self):
		"""🔴 RED ON PURPOSE — item 24's mechanism BREAKS ALL EIGHT LIST VIEWS.

		Found by opening the pages, which is the only way it could have been:
		every metadata assertion in this class is green while the client's entire
		transaction UI shows an empty list.

		`frappe/public/js/frappe/list/list_view.js:382-386`

		    if (this.meta.title_field) {
		        this.columns.push({ type: "Subject", df: get_df(this.meta.title_field) });
		    } else {
		        this.columns.push({ type: "Subject", df: { label: __("ID"), fieldname: "name" } });
		    }

		`get_df` is `frappe.meta.get_docfield`, and **`name` is not a DocField** —
		it returns `undefined`. `get_header_html():695` then reads
		`this.columns[0].df.fieldname` and throws
		`TypeError: Cannot read properties of undefined (reading 'fieldname')`.
		The header never renders and the list shows ZERO rows.

		Measured on yht-test 2026-09-10, signed in as Administrator: `/app/item`
		20 rows, `/app/customer` 8 rows, and all eight of `TITLE_AS_VOUCHER_NO`
		0 rows with that exact TypeError. Note the `else` branch: upstream ALREADY
		labels the subject column "ID" and sorts by `name` when no `title_field`
		is set — so `title_field = "name"` is not merely unsupported, it asks for
		the thing frappe does by default and breaks the page doing it.

		Clearing the Property Setter instead does NOT fix it either:
		`frappe/model/meta.py:318-326` falls back to `"title"` before `"name"`
		whenever the doctype HAS a `title` field, which five of these eight do.

		So item 24 needs a different mechanism, and that is a design decision
		rather than a coder's call — see `.pipeline/changes.md`, "Spec Issues".
		This test stays here and stays red until it is made; a green suite over a
		broken page is exactly what this batch already shipped once.
		"""
		for doctype in self.doctypes:
			with self.subTest(doctype=doctype):
				title_field = frappe.get_meta(doctype).title_field
				if not title_field:
					continue
				self.assertIsNotNone(
					frappe.get_meta(doctype).get_field(title_field),
					f"{doctype}: title_field '{title_field}' is not a DocField — "
					"list_view.setup_columns builds an undefined subject column and "
					"get_header_html throws, so the list renders no rows at all",
				)


# ============================================================== item 25


class TestItem25UpdateStockDefault(FrappeTestCase):
	"""`update_stock` opens ticked on a standalone invoice."""

	def tearDown(self):
		frappe.db.rollback()

	def test_the_default_is_set_on_both_invoices(self):
		for doctype in ("Sales Invoice", "Purchase Invoice"):
			with self.subTest(doctype=doctype):
				field = frappe.get_meta(doctype).get_field("update_stock")
				self.assertIsNotNone(field, f"{doctype}.update_stock does not exist")
				self.assertEqual(cstr_default(field), "1", f"{doctype}.update_stock does not default on")

	def test_a_brand_new_document_arrives_ticked(self):
		"""Asserted through `frappe.new_doc`, which is what the desk does — not by
		reading the Property Setter back out of the table it was written to."""
		for doctype in ("Sales Invoice", "Purchase Invoice"):
			with self.subTest(doctype=doctype):
				self.assertEqual(cint(frappe.new_doc(doctype).update_stock), 1)

	def test_the_property_setter_is_field_level(self):
		for doctype in ("Sales Invoice", "Purchase Invoice"):
			with self.subTest(doctype=doctype):
				rows = _property_setters(doctype, "update_stock", "default")
				self.assertTrue(rows, f"{doctype}: no update_stock default Property Setter")
				self.assertEqual(rows[0]["doctype_or_field"], "DocField")
				self.assertEqual(rows[0]["value"], "1")
				self.assertEqual(rows[0]["property_type"], "Text")

	def test_erpnext_still_hides_the_box_once_the_stock_has_moved(self):
		"""The precondition the whole item rests on.

		ERPNext ships `depends_on: eval:doc.items.every((item) => !item.dn_detail)`
		on Sales Invoice and the `pr_detail` twin on Purchase Invoice. The field is
		HIDDEN, not read-only, once a row carries the link — which is why a bare
		`default = 1` breaks the DN→SI flow: the operator cannot untick what they
		cannot see, and `validate_delivery_note` then refuses the save.
		"""
		for doctype, detail in (("Sales Invoice", "dn_detail"), ("Purchase Invoice", "pr_detail")):
			with self.subTest(doctype=doctype):
				depends_on = frappe.get_meta(doctype).get_field("update_stock").depends_on or ""
				self.assertIn(detail, depends_on, f"{doctype}: the shipped depends_on is gone")


def cstr_default(field):
	value = field.get("default")
	return "" if value is None else str(value)


class TestItem25LinkageRule(FrappeTestCase):
	"""The forward `update_stock` decision is a LINKAGE test, not a role test.

	This is the reversal the gate approved (Q1): `_may_bypass` no longer decides
	`update_stock`. Every test here patches `_may_bypass` deliberately, because a
	rule that still reads roles passes a test run as Administrator and fails in a
	branch user's hands — the recorded "test it as a non-bypass user" rule.
	"""

	def setUp(self):
		self.company = _first("Company")
		if not self.company:
			self.skipTest("no company on this site")
		self.restore = []

	def tearDown(self):
		for restore in reversed(self.restore):
			restore()
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _no_bypass(self):
		self.restore.append(_patch(sales_flow, "_may_bypass", lambda user=None: False))

	def _bypass(self):
		self.restore.append(_patch(sales_flow, "_may_bypass", lambda user=None: True))

	@staticmethod
	def _first_mappable(doctype, mapper, filters, limit=25):
		"""The first document of `doctype` the mapper will actually map, or None.

		Every "newest submitted X" fixture in this class hit the same wall: the
		newest one is fully consumed and the MAPPER throws before the rule under
		test runs. Asking the mapper is the only reliable test of "is there
		anything left on this document", so it is asked.
		"""
		for row in frappe.get_all(
			doctype, filters=filters, pluck="name", order_by="creation desc", limit_page_length=limit
		):
			try:
				return mapper(row)
			except Exception:  # nothing left to map on this one — try the next
				continue
		return None

	def _si(self, **row):
		doc = frappe.new_doc("Sales Invoice")
		doc.company = self.company
		doc.update_stock = 1
		if row:
			doc.append("items", row)
		return doc

	def _pi(self, **row):
		doc = frappe.new_doc("Purchase Invoice")
		doc.company = self.company
		doc.update_stock = 1
		if row:
			doc.append("items", row)
		return doc

	# ------------------------------------------------------------- (a) and (h)

	def test_a_branch_user_keeps_the_tick_on_a_standalone_invoice(self):
		"""🔴 THE REVERSAL. Today this forces 0 for every non-bypass user."""
		self._no_bypass()
		doc = self._si(item_code="_dummy", qty=1, rate=10)
		sales_flow.enforce_delivery_note_route(doc)
		self.assertEqual(cint(doc.update_stock), 1)

	def test_the_decision_no_longer_reads_roles_at_all(self):
		"""Bypass and non-bypass must agree. If they differ, the role test survived."""
		outcomes = []
		for setter in (self._no_bypass, self._bypass):
			setter()
			doc = self._si(item_code="_dummy", qty=1, rate=10)
			sales_flow.enforce_delivery_note_route(doc)
			outcomes.append(cint(doc.update_stock))
			self.restore.pop()()
		self.assertEqual(outcomes[0], outcomes[1], "update_stock still depends on the user's roles")

	# ------------------------------------------------------------------- (b)

	def test_an_operator_who_unticks_it_is_left_alone(self):
		self._no_bypass()
		doc = self._si(item_code="_dummy", qty=1, rate=10)
		doc.update_stock = 0
		sales_flow.enforce_delivery_note_route(doc)
		self.assertEqual(cint(doc.update_stock), 0)

	# ------------------------------------------------------------------- (c)

	def test_a_row_carrying_dn_detail_forces_it_off_silently(self):
		"""No msgprint here: ERPNext hides the field, so there is nothing for the
		operator to reconcile and a message would only confuse."""
		self._no_bypass()
		frappe.clear_messages()
		doc = self._si(item_code="_dummy", qty=1, rate=10, dn_detail="SOME-DN-ROW")
		sales_flow.enforce_delivery_note_route(doc)
		self.assertEqual(cint(doc.update_stock), 0)
		self.assertEqual(frappe.get_message_log(), [], "a hidden field must not be explained")

	def test_an_invoice_mapped_from_a_delivery_note_still_saves(self):
		"""🔴 THE REGRESSION `default = 1` WOULD OTHERWISE CAUSE.

		`get_mapped_doc` applies field defaults to the target, so the mapped invoice
		arrives with `update_stock = 1`; `SalesInvoice.validate_delivery_note()`
		then throws "Stock cannot be updated against Delivery Note". The rule has to
		zero it before validation, or the DN→SI flow is dead.
		"""
		from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice

		# 🔴 THE SOURCE HAS TO BE ONE THE MAPPER WILL ACTUALLY MAP, AND
		# `per_billed` DOES NOT ANSWER THAT. The newest submitted note on this
		# site is fully invoiced and `make_sales_invoice` throws "All these items
		# have already been Invoiced/Returned" from `set_missing_values` — before
		# the rule under test is ever reached, so it reads as an item-25 failure
		# and is not one. `per_billed` is status-updater maintained and header
		# level (recorded gotcha 97); it can sit under 100 while every ROW is
		# fully billed. So the candidates are mapped and the first that works is
		# used.
		invoice = self._first_mappable(
			"Delivery Note", make_sales_invoice, {"docstatus": 1, "is_return": 0}
		)
		if invoice is None:
			self.skipTest("no delivery note on this site with anything left to invoice")

		self._no_bypass()
		invoice.insert()  # must not raise
		self.assertEqual(cint(invoice.update_stock), 0)

	def test_a_purchase_invoice_row_carrying_pr_detail_forces_it_off(self):
		"""The purchase side has NO `validate_purchase_receipt` backstop, so a
		`pr_detail` row with `update_stock = 1` silently receives the stock twice.
		This rule is the only thing standing there."""
		self._no_bypass()
		doc = self._pi(item_code="_dummy", qty=1, rate=10, pr_detail="SOME-PR-ROW")
		sales_flow.enforce_purchase_receipt_route(doc)
		self.assertEqual(cint(doc.update_stock), 0)

	def test_a_purchase_invoice_mapped_from_a_receipt_still_saves(self):
		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

		invoice = self._first_mappable(
			"Purchase Receipt", make_purchase_invoice, {"docstatus": 1, "is_return": 0}
		)
		if invoice is None:
			self.skipTest("no purchase receipt on this site with anything left to bill")

		self._no_bypass()
		invoice.insert()  # must not raise
		self.assertEqual(cint(invoice.update_stock), 0)

	# ------------------------------------------------------------------- (d)

	def _so_detail_with_a_delivery(self):
		rows = frappe.db.sql(
			"""select dni.so_detail
			   from `tabDelivery Note Item` dni
			   join `tabDelivery Note` dn on dn.name = dni.parent
			   where dn.docstatus = 1 and dn.is_return = 0
			     and ifnull(dni.so_detail, '') <> ''
			   limit 1""",
			as_dict=True,
		)
		return rows[0].so_detail if rows else None

	def _so_detail_without_a_delivery(self):
		rows = frappe.db.sql(
			"""select soi.name
			   from `tabSales Order Item` soi
			   left join `tabDelivery Note Item` dni on dni.so_detail = soi.name
			   where dni.name is null
			   limit 1""",
			as_dict=True,
		)
		return rows[0].name if rows else None

	def test_a_sales_order_that_already_shipped_forces_it_off_and_says_so(self):
		"""Here the field IS visible, so the flip has to be explained."""
		so_detail = self._so_detail_with_a_delivery()
		if not so_detail:
			self.skipTest("no delivered Sales Order row on this site")

		self._no_bypass()
		frappe.clear_messages()
		doc = self._si(item_code="_dummy", qty=1, rate=10, so_detail=so_detail)
		sales_flow.enforce_delivery_note_route(doc)
		self.assertEqual(cint(doc.update_stock), 0)
		self.assertTrue(frappe.get_message_log(), "the operator was not told why it flipped")

	def test_a_sales_order_with_nothing_shipped_keeps_the_tick(self):
		so_detail = self._so_detail_without_a_delivery()
		if not so_detail:
			self.skipTest("every Sales Order row on this site has been delivered")

		self._no_bypass()
		doc = self._si(item_code="_dummy", qty=1, rate=10, so_detail=so_detail)
		sales_flow.enforce_delivery_note_route(doc)
		self.assertEqual(cint(doc.update_stock), 1)

	def _unbilled_sales_order(self, delivered):
		"""A submitted, not-yet-billed Sales Order, with or without a delivery."""
		if delivered:
			rows = frappe.db.sql(
				"""select distinct so.name
				   from `tabSales Order` so
				   join `tabSales Order Item` soi on soi.parent = so.name
				   join `tabDelivery Note Item` dni on dni.so_detail = soi.name
				   join `tabDelivery Note` dn on dn.name = dni.parent
				   where so.docstatus = 1 and so.per_billed < 100
				     and so.status not in ('Closed', 'On Hold', 'Completed')
				     and dn.docstatus = 1 and dn.is_return = 0
				   order by so.creation desc limit 1""",
				as_dict=True,
			)
		else:
			rows = frappe.db.sql(
				"""select so.name from `tabSales Order` so
				   where so.docstatus = 1 and so.per_billed < 100
				     and ifnull(so.per_delivered, 0) = 0
				     and so.status not in ('Closed', 'On Hold', 'Completed')
				   order by so.creation desc limit 1""",
				as_dict=True,
			)
		return rows[0].name if rows else None

	def test_an_invoice_mapped_from_a_sales_order_still_saves(self):
		"""🔴 THE TEST THE OTHER SALES-ORDER TESTS CANNOT BE. Every one of them
		hand-builds a document with `item_code="_dummy"` and calls the handler
		directly, so a query that raises inside `_stock_document_against` shows up
		as three unrelated errors and NOTHING proves an invoice from a Sales Order
		can be saved at all. This runs the whole path — `get_mapped_doc` →
		`before_validate` → `enforce_delivery_note_route` → `_stock_already_moved`
		→ `_stock_document_against` — against real rows, and inserts.

		The defect it guards: `child.field(spec["stock_order_link"])` raised
		`TypeError: 'PseudoColumn' object is not callable`, because
		`frappe/query_builder/__init__.py:23` replaces pypika's `Selectable.field`
		METHOD with a `PseudoColumn` INSTANCE. Reproduced on this bench. With item
		25's `default = 1` copied onto the target by the mapper, that was EVERY
		invoice raised from a Sales Order, on both the sales and purchase side.

		Both halves matter and they exercise different branches: a delivered order
		reaches the query and must come back with the tick OFF, an undelivered one
		reaches it and must keep the tick ON.
		"""
		from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

		checked = 0
		for delivered in (True, False):
			order = self._unbilled_sales_order(delivered)
			if not order:
				continue
			checked += 1
			with self.subTest(delivered=delivered):
				self._no_bypass()
				invoice = make_sales_invoice(order)
				self.assertTrue(
					any(cstr(row.so_detail).strip() for row in invoice.items),
					f"{order}: the mapper wrote no so_detail — this proves nothing",
				)
				invoice.insert()  # must not raise
				self.assertEqual(
					cint(invoice.update_stock),
					0 if delivered else 1,
					f"{order}: update_stock is wrong for a delivered={delivered} order",
				)
				self.restore.pop()()
		if not checked:
			self.skipTest("no unbilled submitted Sales Order on this site")

	def test_the_sales_order_lookup_is_one_query_not_one_per_row(self):
		"""An N+1 in a `before_validate` hook runs on every save of every invoice."""
		self._no_bypass()

		def run(count):
			doc = self._si()
			for index in range(count):
				doc.append("items", {"item_code": "_dummy", "qty": 1, "rate": 1,
				                     "so_detail": f"SO-ROW-{index}"})
			return len(_count_queries(lambda: sales_flow.enforce_delivery_note_route(doc)))

		few, many = run(2), run(20)
		self.assertEqual(few, many, f"{few} queries for 2 rows, {many} for 20 — that is an N+1")

	# ------------------------------------------------------- untouched cases

	def test_a_return_is_not_this_rule_s_business(self):
		"""`return_flow.enforce_return_stock_route` owns the return case. How the
		goods LEFT decides how they come back, and ERPNext throws when a return
		disagrees with its original."""
		self._no_bypass()
		doc = self._si(item_code="_dummy", qty=-1, rate=10, dn_detail="SOME-DN-ROW")
		doc.is_return = 1
		sales_flow.enforce_delivery_note_route(doc)
		self.assertEqual(cint(doc.update_stock), 1, "the is_return early exit was lost")

	def test_an_expense_purchase_invoice_is_untouched(self):
		self._no_bypass()
		doc = self._pi(item_code="_dummy", qty=1, rate=10, pr_detail="SOME-PR-ROW")
		doc.custom_is_expense_invoice = 1
		sales_flow.enforce_purchase_receipt_route(doc)
		self.assertEqual(cint(doc.update_stock), 1, "the expense early exit was lost")

	def test_a_purchase_return_is_untouched(self):
		self._no_bypass()
		doc = self._pi(item_code="_dummy", qty=-1, rate=10, pr_detail="SOME-PR-ROW")
		doc.is_return = 1
		sales_flow.enforce_purchase_receipt_route(doc)
		self.assertEqual(cint(doc.update_stock), 1)

	# ---------------------------------------------------------- what is KEPT

	def test_the_bypass_helpers_survive_because_other_rules_still_use_them(self):
		"""`lock_submitted_delivery_note` and the DN refresh comment still read
		these. Deleting them alongside the role test would silently unlock every
		submitted Delivery Note."""
		self.assertTrue(callable(getattr(sales_flow, "_may_bypass", None)))
		self.assertTrue(callable(getattr(sales_flow, "may_use_direct_stock", None)))

	# ----------------------------------------------------- whitelisted helper

	def test_the_stock_document_helper_checks_permission_and_returns_a_boolean(self):
		"""Any `@frappe.whitelist()` is a public HTTP endpoint. It must answer
		yes/no and never hand a branch user a document name they cannot read.

		⚠️ `frappe.whitelisted` is keyed by the FUNCTION OBJECT, not by its dotted
		path, and it is a set/list — never a dict. `frappe.is_whitelisted` tests
		`method not in whitelisted`, so membership is the only correct check;
		`.get(...)` raises AttributeError and `"module.fn" in whitelisted` is always
		False, which is a test that fails everything and proves nothing.

		The permission check is read off THIS FUNCTION's own source via
		`inspect.getsource`, not off the whole module — `sales_flow.py` already
		contains `has_permission` in `return_naming_series`, so a whole-file grep
		passes whatever the new endpoint does.
		"""
		helper, found_as = None, None
		for candidate in ("sales_order_has_stock_document", "source_has_stock_document",
		                  "has_stock_document"):
			helper = getattr(sales_flow, candidate, None)
			if helper:
				found_as = candidate
				break
		self.assertIsNotNone(
			helper, "no whitelisted 'does the source already have a stock document?' helper"
		)
		self.assertIn(
			helper, frappe.whitelisted, f"sales_flow.{found_as} is not @frappe.whitelist()'d"
		)

		# `frappe.whitelist()` wraps through `validate_argument_types`, which uses
		# `@wraps`, so `unwrap` recovers the real function and `getsource` gives its
		# own body rather than the wrapper's.
		source = inspect.getsource(inspect.unwrap(helper))
		self.assertIn(
			"has_permission", source, f"{found_as} does not check frappe.has_permission"
		)
		self.assertIn("throw=True", source, f"{found_as} checks permission but does not throw")
		self.assertNotIn(
			"allow_guest", source, f"{found_as} is reachable without a login"
		)


class TestItem25ReturnsSurviveTheDefault(FrappeTestCase):
	"""A credit note still saves once `update_stock` defaults to 1.

	🔴 THE REGRESSION ITEM 25 CAUSED IN A MODULE IT NEVER TOUCHED. Where the source
	of a mapped credit note has no `update_stock` field of its own — which is
	exactly `delivery_note.make_sales_invoice`, the mapper `multi_return.py:236`
	uses — `get_mapped_doc` falls back to the TARGET's field default, so from item
	25 on every such credit note arrives ticked.
	`erpnext/controllers/sales_and_purchase_return.py:77` then throws *"'Update
	Stock' can not be checked because items are not delivered via {0}"* because the
	invoice being reversed did not carry its own stock.

	🔴 AND IT HAD TO BE TESTED AS A BYPASS USER — the inverse of the recorded "test
	it as a non-bypass user" rule, and the case that actually broke.
	`enforce_return_stock_route` returned early for any bypass role, so the guard
	that zeroes the flag never ran for a System Manager, Stock Manager or Accounts
	Manager — precisely the roles that raise credit notes. A Branch User was fine.
	The fix moves the zeroing ABOVE the bypass check; these tests pin it there.
	"""

	def setUp(self):
		self.flow = _module("return_flow")
		self.restore = []
		self.source = self._returnable_dn_delivered_invoice()
		if not self.source:
			self.skipTest("no returnable DN-delivered invoice on this site to credit")

	@staticmethod
	def _returnable_dn_delivered_invoice():
		"""A DN-delivered invoice that a return can still be mapped from.

		🔴 "NO SALES INVOICE RETURN AGAINST IT" IS NOT "RETURNABLE", and the
		difference is a whole round of misread failures. `update_item` sets
		`qty = -1 * (source.qty - already_returned)`, and `already_returned`
		counts the DELIVERY-side returns too — so a filter that only excludes
		`tabSales Invoice` returns happily picks an invoice whose mapped credit
		note comes back with every row at qty 0. ERPNext then throws *"Atleast
		one item should be entered with negative quantity"* out of
		`validate_returned_items`, which looks exactly like the bug under test
		and is not it. So the candidates are MAPPED and the first one that
		actually carries a negative row is used.
		"""
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		rows = frappe.db.sql(
			"""select si.name
			   from `tabSales Invoice` si
			   join `tabSales Invoice Item` sii on sii.parent = si.name
			   where si.docstatus = 1 and si.is_return = 0 and si.update_stock = 0
			     and si.is_pos = 0 and ifnull(sii.dn_detail, '') <> ''
			   group by si.name order by si.creation desc limit 25""",
			as_dict=True,
		)
		for row in rows:
			try:
				note = make_return_doc("Sales Invoice", row.name)
			except Exception:  # over-returned, consolidated, or otherwise unmappable
				continue
			if any(flt(item.qty) < 0 for item in note.get("items") or []):
				return row.name
		return None

	def tearDown(self):
		for restore in reversed(self.restore):
			restore()
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _credit_note(self):
		"""A credit note in the state the Delivery-Note-sourced mapper leaves it in.

		`make_return_doc` copies the SOURCE invoice's own `update_stock` (0), so it
		does not reproduce the bug on its own; the `delivery_note.make_sales_invoice`
		path has no source field to copy and takes the default. Setting it here is
		that state, without dragging a whole delivery-return fixture in.
		"""
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		note = make_return_doc("Sales Invoice", self.source)
		note.update_stock = 1
		return note

	def test_a_bypass_user_can_raise_a_credit_note_against_a_dn_delivered_invoice(self):
		"""🔴 THE ONE THAT BROKE. Administrator is a bypass role by definition."""
		self.restore.append(_patch(sales_flow, "_may_bypass", lambda user=None: True))
		note = self._credit_note()
		note.insert()  # must not raise
		self.assertEqual(
			cint(note.update_stock),
			0,
			"the credit note kept update_stock — erpnext refuses it for a bypass user",
		)

	def test_a_branch_user_gets_the_same_answer(self):
		"""The pair. If these two disagree the guard is back below the bypass line."""
		self.restore.append(_patch(sales_flow, "_may_bypass", lambda user=None: False))
		note = self._credit_note()
		note.insert()  # must not raise
		self.assertEqual(cint(note.update_stock), 0)

	def test_the_zeroing_happens_before_the_bypass_check_not_after(self):
		"""Asserted through the handler on both sides, so the ORDER is what is
		pinned rather than one lucky outcome."""
		outcomes = []
		for allowed in (True, False):
			self.restore.append(_patch(sales_flow, "_may_bypass", lambda user=None, a=allowed: a))
			note = self._credit_note()
			self.flow.enforce_return_stock_route(note)
			outcomes.append(cint(note.update_stock))
			self.restore.pop()()
		self.assertEqual(outcomes, [0, 0], f"bypass={outcomes[0]}, branch={outcomes[1]}")

	def test_a_return_of_a_direct_stock_invoice_still_brings_the_goods_back(self):
		"""The control. Zeroing must be conditional on the ORIGINAL, or a return of
		a legacy direct-stock invoice can never put the stock back — the exact
		regression the 2026-08-26 `is_return` branch was added to fix."""
		original = _first(
			"Sales Invoice",
			{"docstatus": 1, "is_return": 0, "update_stock": 1, "is_pos": 0},
			order_by="creation desc",
		)
		if not original:
			self.skipTest("no submitted direct-stock invoice on this site")

		self.restore.append(_patch(sales_flow, "_may_bypass", lambda user=None: True))
		note = frappe.new_doc("Sales Invoice")
		note.is_return = 1
		note.return_against = original
		note.update_stock = 1
		self.flow.enforce_return_stock_route(note)
		self.assertEqual(
			cint(note.update_stock), 1, "a return of a direct-stock invoice was stripped of its stock"
		)


class TestItem25ClientRule(FrappeTestCase):
	"""`public/js/sales_flow.js` and its cache-busting version."""

	def test_the_handler_covers_both_invoices(self):
		source = _source("public/js/sales_flow.js")
		self.assertIn("Purchase Invoice", source, "no Purchase Invoice twin")
		self.assertIn("dn_detail", source)
		self.assertIn("pr_detail", source)

	def test_the_old_role_driven_apply_si_is_gone(self):
		"""25.4 REPLACES `apply_si`.

		Leaving it in place means the client still greys the box out for a branch
		user off the role answer, so the server says "keep the tick" and the form
		says "you may not" — the reversal half-lands and reads as a bug. It also
		still does `if (frm.is_new()) frm.set_value("update_stock", 0)`, which
		un-ticks the new default on every fresh form.
		"""
		source = _source("public/js/sales_flow.js")
		self.assertNotIn("apply_si", source, "the old role-driven handler survived")
		self.assertNotRegex(
			source,
			r"is_new\(\)\s*\)?\s*frm\.set_value\(\s*[\"']update_stock[\"']\s*,\s*0",
			"the client still zeroes update_stock on a new form, defeating the new default",
		)

	def test_the_delivery_note_role_comment_is_KEPT(self):
		"""The complement, and the reason this is not a delete-everything change.

		`_may_bypass` / `may_use_direct_stock` are explicitly KEPT (spec 25.1) —
		`lock_submitted_delivery_note` and the Delivery Note refresh comment still
		read them. They simply stop deciding `update_stock`. A rewrite that rips the
		role check out of the whole FILE silently drops the "this note is submitted
		and locked" comment, which is a different feature.
		"""
		source = _source("public/js/sales_flow.js")
		self.assertIn(
			"may_use_direct_stock",
			source,
			"the Delivery Note lock comment lost its role check along with apply_si",
		)

	def test_the_field_is_made_read_only_not_hidden(self):
		"""`frm.set_df_property` on a HEADER field is safe — recorded gotcha 53 is
		about grid cells, which need the six-argument per-row form. And it must be
		`read_only`, not `hidden`: the operator has to SEE that the box is off and
		why, which is the whole point of the msgprint on the Sales Order path."""
		source = _source("public/js/sales_flow.js")
		self.assertIn("set_df_property", source, "the lock is not applied through set_df_property")
		self.assertRegex(
			source,
			r"set_df_property\(\s*[\"']update_stock[\"']\s*,\s*[\"']read_only[\"']",
			"update_stock is not being made read_only",
		)
		self.assertNotRegex(
			source,
			r"set_df_property\(\s*[\"']update_stock[\"']\s*,\s*[\"']hidden[\"']",
			"update_stock is hidden rather than read-only — the operator cannot see why it is off",
		)

	def test_the_handler_runs_on_both_onload_and_refresh(self):
		"""`refresh` alone misses the first paint of a mapped document; `onload`
		alone misses a re-render after the items grid changes."""
		source = _source("public/js/sales_flow.js")
		for event in ("onload", "refresh"):
			with self.subTest(event=event):
				self.assertIn(event, source, f"the handler is not registered on {event}")

	def test_the_asset_version_was_bumped(self):
		"""🔴 Without the bump every already-loaded browser keeps the old file
		forever — nginx sends no Cache-Control for /assets."""
		includes = frappe.get_hooks("app_include_js", app_name="yht_custom") or []
		sales_flow_js = [entry for entry in includes if "sales_flow.js" in entry]
		self.assertTrue(sales_flow_js, "sales_flow.js is not included")
		self.assertNotIn("?v=9", sales_flow_js[0], "sales_flow.js changed but ?v= was not bumped")


# ============================================================== item 27


class TestItem27GlobalSearchPurge(FrappeTestCase):
	"""Purge orphan `__global_search` rows, chunked and re-runnable.

	🔴 `__global_search` is MyISAM. There is no transaction and
	`frappe.db.rollback()` cannot undo a single delete here, so every fixture row
	this class inserts is removed in a `finally` whatever happens.
	"""

	MISSING_DOCTYPE = "_Test YHT Batch3 Vanished DocType"
	ORPHAN_NAME = "_TEST-YHT-BATCH3-ORPHAN"

	def setUp(self):
		self.purge = _module("global_search_purge")
		self.inserted = []
		self.real_name = _first("Sales Invoice", {"docstatus": 1})
		if not self.real_name:
			self.skipTest("no submitted Sales Invoice to anchor a real row against")

	def tearDown(self):
		# 🔴 The rollback must run even if the MyISAM cleanup throws, and every row
		# must be attempted even if one of them throws. `purge()` COMMITS between
		# batches (it has to — MyISAM has no transaction), so by the time we get
		# here the class-level rollback can no longer undo anything this test did
		# to `__global_search`. These deletes are the only cleanup there is.
		try:
			self._cleanup()
		finally:
			frappe.db.rollback()

	def _cleanup(self):
		errors = []
		for doctype, name in self.inserted:
			try:
				frappe.db.sql(
					"delete from `__global_search` where doctype = %s and name = %s",
					(doctype, name),
				)
			except Exception as exc:  # one bad row must not strand the others
				errors.append(f"{doctype}/{name}: {exc}")
		self.inserted = []
		if errors:
			raise AssertionError("fixture rows left behind in __global_search: " + "; ".join(errors))

	def _insert(self, doctype, name):
		existing = frappe.db.sql(
			"select 1 from `__global_search` where doctype = %s and name = %s", (doctype, name)
		)
		if existing:
			return False
		frappe.db.sql(
			"""insert into `__global_search` (doctype, name, title, content, route, published)
			   values (%s, %s, %s, %s, %s, 0)""",
			(doctype, name, name, "batch3 fixture", f"/app/{frappe.scrub(doctype)}/{name}"),
		)
		self.inserted.append((doctype, name))
		return True

	def _rows(self, doctype, name):
		return frappe.db.sql(
			"select 1 from `__global_search` where doctype = %s and name = %s", (doctype, name)
		)

	def _purge(self, **kwargs):
		"""Every purge in this class runs SCOPED, and with nothing of ours pending.

		🔴 TWO HAZARDS, BOTH MEASURED, AND NEITHER IS HYPOTHETICAL. An earlier
		version of this class called `purge()` unscoped six times; the run deleted
		roughly **209,000** rows of the site's live `__global_search` on top of the
		219,430 the migrate patch took, and none of it is recoverable except by the
		full-table rebuild this module's own docstring forbids.

		1. **Volume.** `doctypes=` is a hard filter in `_doctype_counts`, so a
		   scoped call can never walk the whole index. Every call below names the
		   doctype its own fixture rows sit under, or bounds itself with
		   `time_budget`. This helper FAILS the test rather than let an unscoped
		   call through — the rule has to be enforceable, not just observed.
		2. **The commit.** `purge()` commits between pages
		   (`global_search_purge.py:202`) because MyISAM has no transaction, and a
		   commit inside a test makes whatever the enclosing transaction was
		   holding permanent (recorded gotcha 74). That is the likeliest source of
		   one invoice name turning up in two different test modules. Rolling back
		   first leaves the commit nothing of ours to make permanent; the fixture
		   rows are raw SQL against a non-transactional table, so they survive it.
		"""
		if not kwargs.get("doctypes") and kwargs.get("time_budget") is None:
			self.fail("a purge() in this suite must be scoped with doctypes= or time_budget=")
		frappe.db.rollback()
		return self.purge.purge(**kwargs)

	# ------------------------------------------------------------------ report

	def test_report_writes_nothing(self):
		"""This is the output that goes into the deploy record BEFORE any delete."""
		self._insert("Sales Invoice", self.ORPHAN_NAME)
		before = frappe.db.sql("select count(*) from `__global_search`")[0][0]
		result = self.purge.report()
		after = frappe.db.sql("select count(*) from `__global_search`")[0][0]
		self.assertEqual(before, after, "report() deleted rows")
		self.assertIsInstance(result, dict)

	def test_report_states_totals_orphans_and_whether_the_table_exists(self):
		result = self.purge.report()
		self.assertTrue(result, "report() returned nothing")
		sample = next(iter(result.values()))
		for key in ("total", "orphans", "table_exists"):
			self.assertIn(key, sample, f"report() rows do not carry '{key}'")

	def test_report_survives_the_collation_mismatch(self):
		"""⚠️ Measured on yht-khobhar 2026-09-10: joining `__global_search` to
		`tabDocType` raises `Illegal mix of collations (utf8mb4_general_ci,
		utf8mb4_unicode_ci)`. An explicit COLLATE is required, and this is the test
		that catches its absence."""
		try:
			self.purge.report()
		except Exception as exc:  # the message IS the assertion
			if "collation" in str(exc).lower():
				self.fail(f"report() hit the collation mismatch: {exc}")
			raise

	# ------------------------------------------------------------------- purge

	def test_an_orphan_goes_and_a_real_row_stays(self):
		self._insert("Sales Invoice", self.ORPHAN_NAME)
		self._insert("Sales Invoice", self.real_name)

		self._purge(batch_size=50, sleep=0, doctypes=["Sales Invoice"])

		self.assertFalse(self._rows("Sales Invoice", self.ORPHAN_NAME), "the orphan survived")
		self.assertTrue(self._rows("Sales Invoice", self.real_name), "a REAL row was deleted")

	def test_a_second_run_deletes_nothing(self):
		"""Idempotent by construction: it only deletes rows it has just proved have
		no record."""
		self._insert("Sales Invoice", self.ORPHAN_NAME)
		self._purge(batch_size=50, sleep=0, doctypes=["Sales Invoice"])
		second = self._purge(batch_size=50, sleep=0, doctypes=["Sales Invoice"])
		self.assertEqual(cint(second.get("deleted")), 0)

	def test_a_doctype_with_no_table_is_reported_and_skipped(self):
		"""Gate Q2: skip by default, report the count. Those rows are the largest
		and least reversible group — every one is an orphan by definition — and an
		uninstalled app may be coming back."""
		self._insert(self.MISSING_DOCTYPE, self.ORPHAN_NAME)

		result = self._purge(batch_size=50, sleep=0, doctypes=[self.MISSING_DOCTYPE])

		self.assertTrue(
			self._rows(self.MISSING_DOCTYPE, self.ORPHAN_NAME),
			"rows for a doctype with no table were purged without an explicit flag",
		)
		skipped = json.dumps(result, default=str)
		self.assertIn(self.MISSING_DOCTYPE, skipped, "the skipped doctype was not reported")

	def test_the_missing_table_rows_go_only_when_asked_explicitly(self):
		self._insert(self.MISSING_DOCTYPE, self.ORPHAN_NAME)
		self._purge(
			batch_size=50, sleep=0, include_missing=True, doctypes=[self.MISSING_DOCTYPE]
		)
		self.assertFalse(self._rows(self.MISSING_DOCTYPE, self.ORPHAN_NAME))

	def test_a_time_budget_stops_cleanly_and_says_it_is_unfinished(self):
		result = self._purge(batch_size=1, sleep=0, time_budget=0)
		self.assertIn("finished", result)
		self.assertIn("deleted", result)
		self.assertIn("remaining_estimate", result)
		self.assertFalse(result["finished"], "a zero time budget reported the job finished")

	def test_purge_can_be_scoped_to_named_doctypes(self):
		"""The manual completion run is `bench execute … purge` repeated; scoping is
		what makes a targeted re-run cheap."""
		self._insert("Sales Invoice", self.ORPHAN_NAME)
		self._purge(batch_size=50, sleep=0, doctypes=["Journal Entry"])
		self.assertTrue(
			self._rows("Sales Invoice", self.ORPHAN_NAME),
			"a doctype outside the requested scope was purged",
		)

	# -------------------------------------------------------------- mechanics

	def test_paging_is_keyset_never_offset(self):
		"""OFFSET skips rows the moment you start deleting behind yourself."""
		source = _source("global_search_purge.py")
		self.assertNotIn("offset", source.lower(), "OFFSET paging cannot survive concurrent deletes")
		self.assertIn("order by", source.lower())

	def test_nothing_rebuilds_or_optimises_the_whole_table(self):
		"""890k rows, MyISAM, table locked throughout — and the box is shared with
		four live client sites."""
		source = _source("global_search_purge.py")
		for forbidden in ("rebuild_for_all_doctypes", "rebuild-global-search", "OPTIMIZE TABLE"):
			self.assertNotIn(forbidden, source, f"{forbidden} must never run here")

	def test_it_sleeps_between_batches(self):
		source = _source("global_search_purge.py")
		self.assertIn("sleep", source, "no pause between batches — this is a shared box")

	def test_the_patch_exists_and_is_registered(self):
		self.assertTrue(
			os.path.exists(os.path.join(APP_ROOT, "patches", "purge_orphan_global_search.py")),
			"yht_custom/patches/purge_orphan_global_search.py is missing",
		)
		self.assertIn("purge_orphan_global_search", _source("patches.txt"))

	def test_the_patch_bounds_itself_so_a_routine_migrate_stays_safe(self):
		source = _source("patches/purge_orphan_global_search.py")
		self.assertIn("time_budget", source, "the patch does not bound its own runtime")

	def test_the_patch_deletes_nothing_unless_the_site_opts_in(self):
		"""🔴 Gate Q11, as a test. `bench migrate` IS the deploy step, so a patch
		that deletes on sight destroys rows BEFORE the pre-flight `report()` the
		runbook requires — 219,430 of them in 122 s on yht-test, unattended. It is
		gated on a `site_config.json` flag instead, and the gate is asserted by
		RUNNING the patch with the flag off and counting rows, not by reading the
		source: a flag that is read and then ignored greps identically.
		"""
		patch = importlib.import_module("yht_custom.patches.purge_orphan_global_search")
		flag = _attr(patch, "SITE_CONFIG_FLAG")
		if cint(frappe.conf.get(flag)):
			self.skipTest(f"{flag} is set on this site — the gate is open by configuration")

		self._insert(self.MISSING_DOCTYPE, self.ORPHAN_NAME)
		before = frappe.db.sql("select count(*) from `__global_search`")[0][0]
		patch.execute()
		after = frappe.db.sql("select count(*) from `__global_search`")[0][0]

		self.assertEqual(before, after, "the patch deleted rows with the site flag unset")
		self.assertTrue(self._rows(self.MISSING_DOCTYPE, self.ORPHAN_NAME))


# ============================================================== item 28


OTHER_REMARKS = "custom_other_remarks"
OTHER_REMARKS_DOCTYPES = (
	"Sales Invoice",
	"Purchase Invoice",
	"Delivery Note",
	"Purchase Receipt",
	"Payment Entry",
	"Journal Entry",
	"Sales Order",
	"Quotation",
	"Stock Entry",
	"Material Request",
	"Stock Reconciliation",
)
TRACK_CHANGES_OFF_UPSTREAM = ("Quotation", "Stock Entry", "Material Request", "Stock Reconciliation")


class TestItem28OtherRemarksField(FrappeTestCase):
	"""A new "Other Remarks", editable after submit, on eleven transaction doctypes."""

	def setUp(self):
		self.module = _module("other_remarks")

	def tearDown(self):
		frappe.db.rollback()

	def test_the_module_constants_say_what_the_spec_says(self):
		self.assertEqual(_attr(self.module, "FIELDNAME"), OTHER_REMARKS)
		self.assertEqual(set(_attr(self.module, "DOCTYPES")), set(OTHER_REMARKS_DOCTYPES))

	def test_the_fieldname_is_not_custom_remarks(self):
		"""🔴 `custom_remarks` is TAKEN on this site.

		`zatca_vat_report` owns a Check field of that name on Payment Entry, and
		`setup.py` owns a Small Text of that name on Opening Invoice Creation Tool
		Item. Reusing it would collide with a live field of a different TYPE.
		"""
		self.assertNotEqual(_attr(self.module, "FIELDNAME"), "custom_remarks")
		existing = frappe.get_meta("Payment Entry").get_field("custom_remarks")
		if existing:
			self.assertEqual(
				existing.fieldtype, "Check", "Payment Entry.custom_remarks was overwritten"
			)

	def test_the_field_exists_everywhere_and_is_editable_after_submit(self):
		for doctype in OTHER_REMARKS_DOCTYPES:
			with self.subTest(doctype=doctype):
				field = frappe.get_meta(doctype).get_field(OTHER_REMARKS)
				self.assertIsNotNone(field, f"{doctype}.{OTHER_REMARKS} was never created")
				self.assertEqual(field.fieldtype, "Small Text")
				self.assertEqual(cint(field.allow_on_submit), 1, "not editable after submit")
				self.assertEqual(cint(field.print_hide), 1)
				self.assertEqual(cint(field.no_copy), 0)
				self.assertTrue(field.description, "no description explaining it is a note only")

	def test_no_field_landed_at_the_end_of_its_form(self):
		"""🔴 `update_field_order_based_on_insert_after` appends a custom field with
		an unresolvable `insert_after` to the very END of the form, silently. A
		remarks box below the Amended From line is not what anybody asked for."""
		for doctype in OTHER_REMARKS_DOCTYPES:
			with self.subTest(doctype=doctype):
				order = [df.fieldname for df in frappe.get_meta(doctype).fields]
				if OTHER_REMARKS not in order:
					self.fail(f"{doctype}: field missing entirely")
				self.assertNotEqual(
					order[-1], OTHER_REMARKS, f"{doctype}: the field fell to the end of the form"
				)

	def test_every_resolved_anchor_actually_exists(self):
		"""A doctype whose anchor cannot be resolved must be logged and SKIPPED, so
		the anchor recorded on the Custom Field has to be a real field."""
		for doctype in OTHER_REMARKS_DOCTYPES:
			anchor = frappe.db.get_value(
				"Custom Field", {"dt": doctype, "fieldname": OTHER_REMARKS}, "insert_after"
			)
			if not anchor:
				self.fail(f"{doctype}: no Custom Field record for {OTHER_REMARKS}")
			with self.subTest(doctype=doctype):
				self.assertIsNotNone(
					frappe.get_meta(doctype).get_field(anchor),
					f"{doctype}: insert_after points at '{anchor}', which does not exist",
				)

	def test_track_changes_is_on_everywhere_so_the_activity_log_records_the_edit(self):
		"""`Document.save_version()` returns early unless the DocType has
		`track_changes = 1`. Without it the client's "view it in the activity log"
		premise silently produces nothing."""
		for doctype in OTHER_REMARKS_DOCTYPES:
			with self.subTest(doctype=doctype):
				self.assertEqual(cint(frappe.get_meta(doctype).track_changes), 1)

	def test_the_four_that_ship_with_it_off_get_a_doctype_level_property_setter(self):
		for doctype in TRACK_CHANGES_OFF_UPSTREAM:
			with self.subTest(doctype=doctype):
				rows = [
					row
					for row in _doctype_property_setter(doctype, "track_changes")
					if not row.get("field_name")
				]
				self.assertTrue(rows, f"{doctype}: no track_changes Property Setter")
				self.assertEqual(rows[0]["doctype_or_field"], "DocType")
				self.assertEqual(str(rows[0]["value"]), "1")

	def test_every_name_is_in_the_fixture_filter(self):
		"""🔴 A fixture needs BOTH the record AND its name in the filter list. A
		name missing here is silently not exported, and the field never reaches the
		next site."""
		names = set()
		for entry in frappe.get_hooks("fixtures", app_name="yht_custom") or []:
			if not isinstance(entry, dict) or entry.get("dt") != "Custom Field":
				continue
			for clause in entry.get("filters") or []:
				if len(clause) == 3 and clause[0] == "name" and clause[1] == "in":
					names.update(clause[2])
		for doctype in OTHER_REMARKS_DOCTYPES:
			with self.subTest(doctype=doctype):
				self.assertIn(f"{doctype}-{OTHER_REMARKS}", names)

	def test_the_step_is_registered_and_independent(self):
		self.assertIn("ensure_other_remarks_fields", setup.PROVISIONING_STEPS)


class TestItem28OtherRemarksAfterSubmit(FrappeTestCase):
	"""Editing it on a SUBMITTED document, which is the whole point of the field."""

	def setUp(self):
		_module("other_remarks")
		self.restore = []

	def tearDown(self):
		for restore in reversed(self.restore):
			restore()
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_editing_it_on_a_submitted_invoice_succeeds_and_is_versioned(self):
		name = _first("Sales Invoice", {"docstatus": 1}, order_by="creation desc")
		if not name:
			self.skipTest("no submitted Sales Invoice on this site")

		before = frappe.db.count("Version", {"ref_doctype": "Sales Invoice", "docname": name})
		doc = frappe.get_doc("Sales Invoice", name)
		doc.set(OTHER_REMARKS, f"batch3 {uuid.uuid4().hex[:8]}")

		# 🔴 `ignore_version=False` IS LOAD-BEARING, NOT TIDINESS.
		# `frappe/model/document.py:397` reads
		# `self.flags.ignore_version = frappe.flags.in_test if ignore_version is None
		# else ignore_version`, so under `bench run-tests` a plain `doc.save()` writes
		# NO `Version` row and the assertion below could never pass. Passing it
		# explicitly tests what a desk save does, which is what the client sees in
		# the activity log.
		doc.save(ignore_version=False)

		self.assertEqual(
			frappe.db.count("Version", {"ref_doctype": "Sales Invoice", "docname": name}),
			before + 1,
			"no Version row — the activity log will show nothing",
		)

	def test_a_plain_branch_user_may_edit_it_on_a_submitted_delivery_note(self):
		"""🔴 THE COLLISION. `sales_flow.lock_submitted_delivery_note` throws for ANY
		changed field outside its `permitted` set, for every non-bypass user. Unless
		`custom_other_remarks` is added to that set the new field is unusable on a
		Delivery Note — which is the doctype the client most wants it on.

		Run with `_may_bypass` forced off: an exemption tested only as a bypass user
		is not tested at all.
		"""
		name = _first("Delivery Note", {"docstatus": 1}, order_by="creation desc")
		if not name:
			self.skipTest("no submitted Delivery Note on this site")

		self.restore.append(_patch(sales_flow, "_may_bypass", lambda user=None: False))
		doc = frappe.get_doc("Delivery Note", name)
		doc.load_doc_before_save()
		doc.set(OTHER_REMARKS, f"batch3 {uuid.uuid4().hex[:8]}")

		sales_flow.lock_submitted_delivery_note(doc)  # must not raise

	def test_the_delivery_note_lock_still_refuses_everything_else(self):
		"""The control that proves the test above is not passing because the lock
		was simply disabled."""
		name = _first("Delivery Note", {"docstatus": 1}, order_by="creation desc")
		if not name:
			self.skipTest("no submitted Delivery Note on this site")

		self.restore.append(_patch(sales_flow, "_may_bypass", lambda user=None: False))
		doc = frappe.get_doc("Delivery Note", name)
		doc.load_doc_before_save()
		doc.set(OTHER_REMARKS, "batch3")
		doc.customer_name = f"{doc.customer_name} EDITED"

		with self.assertRaises(frappe.ValidationError):
			sales_flow.lock_submitted_delivery_note(doc)

	def test_it_never_reaches_the_ledger(self):
		"""`accounts_controller.py:1371` stamps `self.get("remarks") or
		self.get("remark")` onto every GL Entry. Nothing reads the new field — and
		this asserts that stays true."""
		self.assertIsNone(
			frappe.get_meta("GL Entry").get_field(OTHER_REMARKS),
			"GL Entry grew a custom_other_remarks field",
		)

		company = _first("Company")
		template = frappe.db.get_value(
			"Sales Invoice",
			{"docstatus": 1, "is_return": 0, "company": company, "update_stock": 0, "is_pos": 0},
			"name",
			order_by="modified desc",
		)
		if not template:
			self.skipTest("no submitted non-POS invoice to model")

		marker = f"BATCH3-{uuid.uuid4().hex[:10].upper()}"
		invoice = frappe.copy_doc(frappe.get_doc("Sales Invoice", template))
		invoice.posting_date = today()
		invoice.set_posting_time = 1
		invoice.due_date = today()
		invoice.update_stock = 0
		invoice.is_return = 0
		invoice.is_pos = 0
		invoice.payments = []
		invoice.payment_schedule = []
		for row in invoice.items:
			row.delivery_note = None
			row.dn_detail = None
			row.sales_order = None
			row.so_detail = None
		invoice.set(OTHER_REMARKS, marker)
		invoice.insert()
		invoice.reload()
		invoice.submit()

		entries = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Sales Invoice", "voucher_no": invoice.name},
			fields=["*"],
		)
		self.assertTrue(entries, "the invoice posted no GL Entry — the test proves nothing")
		for entry in entries:
			self.assertNotIn(
				marker,
				json.dumps(entry, default=str),
				"Other Remarks leaked onto the ledger",
			)


# ============================================================== item 29


#: `address_title` is NOT in this list — it is GATED rather than hidden. See
#: `test_a_link_less_address_with_no_short_address_is_not_a_dead_end`.
ADDRESS_HIDDEN = ("email_id", "phone", "fax")
ADDRESS_LEFT_STANDARD = ("address_type", "address_line1", "pincode", "city", "country")
ADDRESS_ARABIC = (
	"custom_address_line1_arabic",
	"custom_area_arabic",
	"custom_city_arabic",
	"custom_country_arabic",
)
#: The six custom fields item 29 asked to reposition. Every one of them turned
#: out to be re-applied by an installed app on every migrate, so gate Q8's stop
#: condition fired on all six and `CUSTOM_FIELD_MOVES["Address"]` moves none of
#: them — see `test_no_custom_field_move_fights_an_app_that_re_applies_it`.
ADDRESS_MOVED_CUSTOM = (*ADDRESS_ARABIC, "custom_building_number", "custom_area")


class TestItem29AddressForm(FrappeTestCase):
	"""Address: trimmed, and English left / Arabic right.

	The rendered layout itself is checked BY EYE on yht-test — a suite cannot see a
	page, and a field takes its section from where it lands in `field_order`. What
	is asserted here is everything a screenshot cannot prove: nothing was dropped,
	nothing became mandatory, and no other app's fixture is being fought.
	"""

	def tearDown(self):
		frappe.db.rollback()

	def test_the_four_fields_the_client_does_not_want_are_hidden(self):
		self.assertIn("Address", form_layout.HIDE_FIELDS, "no Address entry in HIDE_FIELDS")
		configured = set(form_layout.HIDE_FIELDS["Address"])
		self.assertTrue(set(ADDRESS_HIDDEN) <= configured)
		meta = frappe.get_meta("Address")
		for fieldname in ADDRESS_HIDDEN:
			with self.subTest(fieldname=fieldname):
				field = meta.get_field(fieldname)
				self.assertIsNotNone(field, f"Address.{fieldname} does not exist")
				self.assertTrue(field.hidden, f"Address.{fieldname} is still visible")

	def test_address_title_is_gated_not_renamed_or_removed(self):
		"""`Address.autoname` builds the document NAME from `address_title`, and
		`saudi_address.before_insert` already copies `custom_short_address` into it.
		Keeping it off the screen gives the client what they asked for with no
		rename and no data change; removing or renaming it would break naming on
		every new address.

		⚠️ GATED, NOT HIDDEN — see the sibling below for the failure a hard hide
		caused. `depends_on` is client-side only, so nothing about naming, `reqd`
		or validation changes with it.

		⚠️ NO `reqd` ASSERTION HERE, AND THAT IS DELIBERATE. Upstream ships
		`address_title` as a bare `{"fieldname", "fieldtype", "label"}` with no
		`reqd` at all (verified in `frappe/contacts/doctype/address/address.json`),
		so an `assertEqual(cint(field.reqd), 1)` could never pass and it contradicted
		`test_nothing_became_mandatory_or_stopped_being_mandatory`, which is the
		sibling that owns that question. What actually protects naming is
		`Address.autoname` plus `saudi_address.before_insert` filling the field, and
		`test_the_reorder_is_registered_and_drops_nothing` proves it is still on the
		form.
		"""
		field = frappe.get_meta("Address").get_field("address_title")
		self.assertIsNotNone(field)
		self.assertFalse(
			cint(field.hidden),
			"address_title is hidden outright — a link-less new Address then fails "
			"to save pointing at a field that is not on the screen",
		)
		self.assertEqual(
			cstr(field.depends_on).replace(" ", ""),
			"eval:!doc.custom_short_address",
			"address_title must show exactly when there is no Short Address",
		)

	def test_a_link_less_address_with_no_short_address_is_not_a_dead_end(self):
		"""🔴 THE REGRESSION A HARD HIDE CAUSED, ASSERTED THROUGH AN ACTUAL SAVE.

		`frappe/contacts/doctype/address/address.py` throws *"Address Title is
		mandatory."* when `address_title` is blank AND the document carries no
		`links` row, and `saudi_address.before_insert` fills it from
		`custom_short_address` only when the short code is present — which
		`saudi_address` deliberately does not require. So *New Address* from the
		Address list, no party linked, Short Address blank was refused pointing at
		an invisible field: the same shape item 33 avoided on Payment Entry.

		Either outcome is acceptable — it saves, or it is refused naming a field
		the operator can see. What is NOT acceptable is being refused over a
		hidden one.
		"""
		country = frappe.db.get_value("Country", {}, "name")
		if not country:
			self.skipTest("no Country records on this site")

		doc = frappe.new_doc("Address")
		doc.address_type = "Billing"
		doc.address_line1 = "_test yht batch3 street"
		doc.city = "Al Khobar"
		doc.country = country
		# No `links` row and no Short Address — the exact state that used to fail.
		self.assertFalse(doc.get("links"))
		self.assertFalse(doc.get("custom_short_address"))

		try:
			doc.insert()
		except frappe.ValidationError as exc:
			message = cstr(exc)
			meta = frappe.get_meta("Address")
			field = meta.get_field("address_title")
			self.assertIn(
				cstr(field.label),
				message,
				f"the save was refused for something other than Address Title: {message}",
			)
			self.assertFalse(
				cint(field.hidden),
				f"refused with {message!r}, naming a field that is not on the form",
			)
			self.assertEqual(
				cstr(field.depends_on).replace(" ", ""),
				"eval:!doc.custom_short_address",
				f"refused with {message!r}, and the gate does not show the field in this state",
			)

	def test_short_address_is_the_one_on_show(self):
		field = frappe.get_meta("Address").get_field("custom_short_address")
		self.assertIsNotNone(field, "custom_short_address does not exist")
		self.assertFalse(field.hidden, "the field replacing Address Title is itself hidden")

	def test_the_reorder_is_registered_and_drops_nothing(self):
		field_layout = importlib.import_module("yht_custom.field_layout")
		self.assertIn("Address", field_layout.FIELD_MOVES, "no Address entry in FIELD_MOVES")

		order = json.loads(
			frappe.db.get_value(
				"Property Setter",
				{"doc_type": "Address", "property": "field_order", "doctype_or_field": "DocType"},
				"value",
			)
			or "[]"
		)
		self.assertTrue(order, "no Address field_order Property Setter was written")
		self.assertEqual(len(order), len(set(order)), "a fieldname appears twice in field_order")

		shipped = {
			df.fieldname
			for df in frappe.get_meta("Address").fields
			if not df.get("is_custom_field")
		}
		missing = shipped - set(order)
		self.assertFalse(
			missing, f"these standard fields fell out of the form entirely: {sorted(missing)}"
		)

	def test_the_english_column_reads_in_the_client_s_order(self):
		order = [df.fieldname for df in frappe.get_meta("Address").fields]
		positions = [order.index(f) for f in ADDRESS_LEFT_STANDARD if f in order]
		self.assertEqual(len(positions), len(ADDRESS_LEFT_STANDARD), "a left-column field is missing")
		self.assertEqual(positions, sorted(positions), "the English column is out of order")

	@unittest.skip(
		"Item 29's Arabic right-hand column is NOT DELIVERABLE with insert_after. arabic_translation (installed) ships all four Arabic fields in a sync_on_migrate customization file anchored beside their English twins, so it re-positions them on every migrate. The rendered form is a single interleaved column. Open decision."
	)
	def test_the_arabic_fields_sit_in_the_right_hand_column(self):
		order = [df.fieldname for df in frappe.get_meta("Address").fields]
		self.assertIn("column_break0", order, "the shipped two-column frame is gone")
		split = order.index("column_break0")
		for fieldname in ADDRESS_ARABIC:
			with self.subTest(fieldname=fieldname):
				self.assertIn(fieldname, order, f"Address.{fieldname} does not exist")
				self.assertGreater(
					order.index(fieldname), split, f"{fieldname} is in the LEFT column"
				)

	def test_nothing_became_mandatory_or_stopped_being_mandatory(self):
		"""29.3, stated explicitly: no `reqd` and no `mandatory_depends_on` is
		written by this item, and `country` stays required as shipped."""
		for prop in ("reqd", "mandatory_depends_on"):
			rows = _doctype_property_setter("Address", prop)
			self.assertFalse(
				rows, f"this item wrote a {prop} Property Setter on Address: {rows}"
			)
		self.assertEqual(cint(frappe.get_meta("Address").get_field("country").reqd), 1)

	def test_no_zatca_required_field_was_hidden(self):
		"""A Standard (B2B) e-invoice needs the district and the building number off
		the Address. Hiding either would break ZATCA silently."""
		meta = frappe.get_meta("Address")
		for fieldname in ("custom_building_number", "custom_area", "city", "country", "pincode"):
			field = meta.get_field(fieldname)
			if not field:
				continue
			with self.subTest(fieldname=fieldname):
				self.assertFalse(field.hidden, f"Address.{fieldname} is ZATCA-required and hidden")

	def test_no_custom_field_move_fights_an_app_that_re_applies_it(self):
		"""🔴 Gate Q8's stop condition, as a test — and `module: NULL` is not it.

		The gate approved the move on the measurement that all ten Address Custom
		Fields carry `module: NULL` and are therefore "not fixture-owned". None of
		the six is owned through the `fixtures` HOOK — measured, every installed
		app except `yht_custom` returns `[]` from it, and `yht_custom`'s three
		Address entries are our own fields — but that is not the mechanism in play.

		`frappe/modules/utils.py::sync_customizations` walks every INSTALLED app's
		`<app>/<module>/custom/<doctype>.json`, and for each file with
		`sync_on_migrate` truthy runs `custom_field.update(d);
		custom_field.db_update()` over every field it names. `insert_after` is one
		of those keys and the `module` column is consulted nowhere. So a field
		listed in such a file is re-anchored on every migrate no matter what we
		write, and moving it is a standing fight with another app.

		BOTH sources are read here, independently of `field_layout`'s own guard —
		a test that called the function under test would prove only that it runs.

		Two assertions, and the second is what stops this going vacuous: no
		configured move may name an owned field, AND all six fields item 29 wanted
		to move must actually BE owned. If `arabic_translation` or
		`ksa_compliance` ever stops shipping one, that half fails and the move
		becomes available again — which is the news worth having.
		"""
		field_layout = importlib.import_module("yht_custom.field_layout")
		prefix = "Address-"
		owned = {}

		for app in frappe.get_installed_apps():
			for entry in frappe.get_hooks("fixtures", app_name=app) or []:
				if not isinstance(entry, dict) or entry.get("dt") != "Custom Field":
					continue
				for clause in entry.get("filters") or []:
					if len(clause) != 3 or clause[1] != "in":
						continue
					for value in clause[2] or []:
						value = cstr(value)
						bare = value[len(prefix) :] if value.startswith(prefix) else value
						owned.setdefault(bare, f"{app} (fixtures hook)")

			for module in (frappe.local.app_modules or {}).get(app) or []:
				folder = frappe.get_app_path(app, module, "custom")
				if not os.path.isdir(folder):
					continue
				for filename in os.listdir(folder):
					if not filename.endswith(".json"):
						continue
					with open(os.path.join(folder, filename), encoding="utf-8") as handle:
						data = json.loads(handle.read())
					if not data.get("sync_on_migrate") or data.get("doctype") != "Address":
						continue
					for field in data.get("custom_fields") or []:
						if field.get("fieldname"):
							owned.setdefault(
								field["fieldname"],
								f"{app} ({module}/custom/{filename}, sync_on_migrate)",
							)

		# The guard has to SEE what this test just worked out, or it is guarding
		# nothing. Its answer is compared against the independent walk rather than
		# used as the source of truth for the assertions below.
		self.assertEqual(
			field_layout.app_owned_custom_fields("Address"),
			set(owned),
			"field_layout's ownership guard disagrees with the files on disk",
		)

		configured = {pair[0] for pair in field_layout.CUSTOM_FIELD_MOVES.get("Address", [])}
		clash = sorted(configured & set(owned))
		self.assertFalse(
			clash,
			"these moves fight an app that re-applies the field's insert_after on "
			f"every migrate: { {name: owned[name] for name in clash} } — gate Q8 says "
			"stop and report rather than move it",
		)

		for fieldname in ADDRESS_MOVED_CUSTOM:
			with self.subTest(fieldname=fieldname):
				self.assertIn(
					fieldname,
					owned,
					"this field is NO LONGER re-applied by another app, so item 29 can "
					"have its position back — re-check CUSTOM_FIELD_MOVES['Address']",
				)


# ============================================================== item 32


class TestItem32DeliveryBacklink(FrappeTestCase):
	"""Write `delivery_note` / `dn_detail` back onto submitted Sales Invoice rows.

	Only the SI-FIRST flow. In the DN-first flow ERPNext's own
	`delivery_note.make_sales_invoice` already writes both fields at creation.
	"""

	def setUp(self):
		self.backlink = _module("delivery_backlink")
		rows = frappe.db.sql(
			"""select dn.customer, dn.company, dni.item_code, dni.warehouse, dni.rate,
			          dni.cost_center
			   from `tabDelivery Note` dn
			   join `tabDelivery Note Item` dni on dni.parent = dn.name
			   where dn.docstatus = 1 and dn.is_return = 0
			   order by dn.creation desc limit 1""",
			as_dict=True,
		)
		if not rows:
			self.skipTest("no submitted delivery note on this site to model")
		self.tmpl = rows[0]

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	# ------------------------------------------------------------- fixtures

	def _invoice(self, qty=10):
		"""A submitted, SI-first invoice: no stock moved, no Sales Order behind it."""
		doc = frappe.new_doc("Sales Invoice")
		doc.customer, doc.company = self.tmpl.customer, self.tmpl.company
		doc.posting_date = today()
		doc.set_posting_time = 1
		doc.due_date = today()
		doc.update_stock = 0
		doc.is_pos = 0
		doc.append(
			"items",
			{
				"item_code": self.tmpl.item_code,
				"qty": qty,
				"rate": self.tmpl.rate,
				"warehouse": self.tmpl.warehouse,
				"cost_center": self.tmpl.cost_center,
			},
		)
		doc.insert()
		doc.reload()
		doc.submit()
		return doc

	def _note_from(self, invoice, qty=None):
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_delivery_note

		note = make_delivery_note(invoice.name)
		note.set_warehouse = self.tmpl.warehouse
		for row in note.items:
			row.warehouse = self.tmpl.warehouse
			row.cost_center = self.tmpl.cost_center
			if qty is not None:
				row.qty = qty
		return note

	def _link(self, si_row):
		return frappe.db.get_value(
			"Sales Invoice Item", si_row, ["delivery_note", "dn_detail"], as_dict=True
		)

	# ------------------------------------------------------------- the reversal

	def test_the_invoice_row_link_fields_are_NOT_allow_on_submit(self):
		"""🔴 Gate Q3, ACCEPTED — the spec's reversal of the requirement stands.

		`frappe.db.set_value` is a direct UPDATE; it never consults
		`allow_on_submit`, and `delivery_return.py` already writes both fields on
		submitted invoices in production without it. Turning it ON makes things
		worse: `Document.update_children()` rewrites every child row on a
		submitted-doc save, so a form loaded before the link was written would
		SILENTLY BLANK it — and that link is what ERPNext's over-return guard and
		`update_billing_status` depend on. A loud refusal beats a silent unlink.
		"""
		meta = frappe.get_meta("Sales Invoice Item")
		for fieldname in ("delivery_note", "dn_detail"):
			with self.subTest(fieldname=fieldname):
				self.assertEqual(
					cint(meta.get_field(fieldname).allow_on_submit),
					0,
					f"{fieldname} became allow_on_submit — a stale form will now silently unlink it",
				)

	def test_a_stale_form_is_refused_loudly_rather_than_unlinking(self):
		"""The pairing with item 28: submitted documents become routinely editable,
		so a stale form is no longer a rare event. It must raise, not overwrite."""
		invoice = self._invoice()
		stale = frappe.get_doc("Sales Invoice", invoice.name)

		note = self._note_from(invoice)
		note.insert()
		note.submit()

		stale.set(OTHER_REMARKS, "stale edit")
		with self.assertRaises(frappe.UpdateAfterSubmitError):
			stale.save()

	# ------------------------------------------------------------- happy path

	def test_submitting_the_note_writes_both_links_onto_the_invoice_row(self):
		invoice = self._invoice()
		row = invoice.items[0].name
		self.assertFalse(any(self._link(row).values()), "the invoice row was already linked")

		note = self._note_from(invoice)
		note.insert()
		note.submit()

		link = self._link(row)
		self.assertEqual(link.delivery_note, note.name)
		self.assertEqual(link.dn_detail, note.items[0].name)

	def test_a_back_linked_note_can_no_longer_be_cancelled_before_its_invoice(self):
		"""🔴 THE WORKFLOW CHANGE ITEM 32 MAKES, asserted rather than discovered.

		`DeliveryNote.on_cancel` calls `check_next_docstatus()`
		(`delivery_note.py:517` → `:701-709`), which throws *"Sales Invoice {0} has
		already been submitted"* while any submitted invoice row carries
		`delivery_note = <this note>`. `doc_events` run AFTER the controller method,
		so the link this item writes now blocks the cancel it would otherwise have
		re-answered. Before item 32 an SI-first note cancelled freely.

		This is ERPNext's ordinary DN-first behaviour arriving in the SI-first flow.
		It is kept rather than defeated: moving the unlink to `before_cancel` would
		blank the link so the cancel sails through, which is the silent unlink of a
		submitted invoice that gate Q3 refused. The way through is to cancel the
		invoice first.

		⚠️ THAT SECOND HALF CANNOT BE ASSERTED IN THE SAME TEST, and the reason is
		worth writing down. `check_next_docstatus` runs from `on_cancel`, i.e. in
		`run_post_save_methods` — AFTER `db_update()` has already written
		`docstatus = 2`. A request rolls that back on the throw; a test does not,
		so the note is already cancelled in this transaction and a second
		`cancel()` gets *"Cannot edit cancelled document"* from
		`check_docstatus_transition`. The refusal is the assertion.
		"""
		invoice = self._invoice()
		row = invoice.items[0].name
		note = self._note_from(invoice)
		note.insert()
		note.submit()
		self.assertEqual(self._link(row).delivery_note, note.name, "the link was never written")

		note.reload()
		with self.assertRaises(frappe.ValidationError) as caught:
			note.cancel()
		self.assertIn(invoice.name, str(caught.exception))

	def test_running_the_handler_twice_changes_nothing(self):
		invoice = self._invoice()
		row = invoice.items[0].name
		note = self._note_from(invoice)
		note.insert()
		note.submit()

		before = self._link(row)
		modified = frappe.db.get_value("Sales Invoice", invoice.name, "modified")
		self.backlink.link_invoice_rows(frappe.get_doc("Delivery Note", note.name))

		self.assertEqual(self._link(row), before)
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", invoice.name, "modified"),
			modified,
			"the parent invoice's `modified` was bumped — use update_modified=False",
		)

	# ------------------------------------------------------------- split delivery

	def test_a_split_delivery_leaves_the_link_blank(self):
		"""The client's decision: blank rather than an arbitrary winner.

		🔴 TWO RULES COMPOSE, AND COVERAGE IS CHECKED FIRST. `_resolve`'s
		`HAVING COUNT(*) = 1` answers "is there exactly one note", and `_apply` then
		asks "does that note cover the line". A 5-of-10 note fails the second rule
		even while it is the only one — so the link is blank from the FIRST submit
		here, not just after the second makes it ambiguous.

		That ordering is deliberate: a partial delivery must never claim the line,
		and a claim that appears and then vanishes is worse than one that never
		appears. The two rules are asserted in isolation by
		`test_a_partial_delivery_leaves_the_link_blank`,
		`test_a_delivery_that_covers_the_line_does_link`, and
		`test_resolve_drops_a_row_two_notes_claim`.
		"""
		invoice = self._invoice(qty=10)
		row = invoice.items[0].name

		first = self._note_from(invoice, qty=5)
		second = self._note_from(invoice, qty=5)
		first.insert()
		second.insert()

		first.submit()
		self.assertFalse(
			self._link(row).dn_detail,
			"5 of 10 is not a delivery of this line, even as the only note",
		)

		second.submit()
		link = self._link(row)
		self.assertFalse(link.delivery_note, "a split delivery must leave the link blank")
		self.assertFalse(link.dn_detail)

	def test_resolve_drops_a_row_two_notes_claim(self):
		"""The ambiguity rule on its own, at the resolver, where the coverage rule
		in `_apply` cannot mask it: two submitted notes citing one invoice row means
		that row is absent from the map entirely."""
		resolve = _attr(self.backlink, "_resolve")
		invoice = self._invoice(qty=10)
		row = invoice.items[0].name

		first = self._note_from(invoice, qty=5)
		second = self._note_from(invoice, qty=5)
		first.insert()
		second.insert()

		first.submit()
		self.assertIn(row, resolve([row]), "one note should resolve, whatever its quantity")

		second.submit()
		self.assertNotIn(row, resolve([row]), "two notes must drop the row from the map")

	def test_cancelling_one_of_two_notes_re_resolves_the_survivor(self):
		"""Cancel is not a reversal — it re-asks the same question with this note
		gone. Both halves of that are asserted here.

		At the resolver the ambiguity genuinely clears: the survivor is once again
		the only note citing the row. `_apply` then still refuses it, because 5 of
		10 does not cover the line — so the stored link stays blank. Cancelling a
		second delivery cannot conjure a claim the first delivery never earned.

		(Renamed from `…_turns_the_ambiguity_back_into_a_link`, which asserted the
		link WAS restored. That was correct before the coverage rule and is not now;
		with two partial notes there is no quantity at which the survivor qualifies,
		so the old expectation is unreachable rather than merely untested.)
		"""
		resolve = _attr(self.backlink, "_resolve")
		invoice = self._invoice(qty=10)
		row = invoice.items[0].name
		first = self._note_from(invoice, qty=5)
		second = self._note_from(invoice, qty=5)
		first.insert()
		second.insert()
		first.submit()
		second.submit()

		second.reload()
		second.cancel()

		resolved = resolve([row])
		self.assertIn(row, resolved, "the survivor should be unambiguous again")
		self.assertEqual(resolved[row][1], first.items[0].name)

		self.assertFalse(
			self._link(row).dn_detail,
			"the survivor is unambiguous but still only covers half the line",
		)

	# ------------------------------------------------------------- so_detail

	def test_a_row_carrying_so_detail_is_skipped(self):
		"""🔴 Gate Q4. Writing `dn_detail` onto a row that also carries `so_detail`
		drives `update_billed_amount_based_on_so`'s `billed_against_so` NEGATIVE —
		it removes the amount from the SUM and then subtracts it again in the loop —
		and a later unbilled Delivery Note row against the same Sales Order picks up
		a negative `billed_amt`. That is silent corruption of a submitted stock
		document. Measured: 41% of candidate rows are skipped, and that gap is
		accepted."""
		invoice = self._invoice()
		row = invoice.items[0].name
		note = self._note_from(invoice)
		note.insert()

		some_so_row = _first("Sales Order Item") or "SOME-SO-ROW"
		frappe.db.set_value("Sales Invoice Item", row, "so_detail", some_so_row,
		                    update_modified=False)

		note.submit()

		link = self._link(row)
		self.assertFalse(
			link.delivery_note, "a row with so_detail was linked — sibling billing will go negative"
		)
		self.assertFalse(link.dn_detail)

	def test_a_real_sales_order_chain_leaves_its_sibling_note_byte_identical(self):
		"""Discovered from the site's own data, because the thing under test is the
		arithmetic ERPNext already does on documents that already exist."""
		rows = frappe.db.sql(
			"""select sii.name si_row, dni.parent note
			   from `tabSales Invoice Item` sii
			   join `tabSales Invoice` si on si.name = sii.parent
			   join `tabDelivery Note Item` dni on dni.si_detail = sii.name
			   join `tabDelivery Note` dn on dn.name = dni.parent
			   where si.docstatus = 1 and si.is_return = 0
			     and dn.docstatus = 1 and dn.is_return = 0
			     and ifnull(sii.so_detail, '') <> ''
			   limit 1""",
			as_dict=True,
		)
		if not rows:
			self.skipTest("no submitted so_detail chain on this site")

		si_row, note_name = rows[0].si_row, rows[0].note
		before_note = frappe.db.get_value(
			"Delivery Note", note_name, ["per_billed", "status"], as_dict=True
		)
		before_rows = frappe.get_all(
			"Delivery Note Item", filters={"parent": note_name}, fields=["name", "billed_amt"],
			order_by="idx",
		)
		before_link = self._link(si_row)

		self.backlink.link_invoice_rows(frappe.get_doc("Delivery Note", note_name))

		self.assertEqual(self._link(si_row), before_link, "the so_detail row was rewritten")
		self.assertEqual(
			frappe.db.get_value("Delivery Note", note_name, ["per_billed", "status"], as_dict=True),
			before_note,
		)
		self.assertEqual(
			frappe.get_all(
				"Delivery Note Item", filters={"parent": note_name}, fields=["name", "billed_amt"],
				order_by="idx",
			),
			before_rows,
		)

	# ------------------------------------------------------------- returns

	def test_our_handler_is_a_no_op_on_a_delivery_return(self):
		"""🔴 The EXACT complement of `delivery_return.link_credit_note_to_delivery_
		return`, which is registered on the SAME event and writes the SAME two
		fields. Neither may ever run on the other's documents."""
		name = _first("Delivery Note", {"docstatus": 1, "is_return": 1}, order_by="creation desc")
		if not name:
			self.skipTest("no submitted delivery return on this site")

		note = frappe.get_doc("Delivery Note", name)
		si_rows = [
			row.si_detail for row in note.items if row.get("si_detail")
		]
		before = {row: self._link(row) for row in si_rows}

		self.backlink.link_invoice_rows(note)

		for row, link in before.items():
			self.assertEqual(self._link(row), link, "our handler wrote to a RETURN's rows")

	def test_both_handlers_are_registered_on_the_same_events(self):
		"""🔴 Registered through `_merge_events`, never in the `doc_events` literal:
		the branch-defaults `doc_events.update({...})` replaces the whole
		"Delivery Note" key and silently drops anything declared up there."""
		events = frappe.get_hooks("doc_events").get("Delivery Note", {})
		for event, ours, theirs in (
			(
				"on_submit",
				"yht_custom.delivery_backlink.link_invoice_rows",
				"yht_custom.delivery_return.link_credit_note_to_delivery_return",
			),
			(
				"on_cancel",
				"yht_custom.delivery_backlink.unlink_invoice_rows",
				"yht_custom.delivery_return.unlink_credit_note_from_delivery_return",
			),
		):
			handlers = events.get(event) or []
			if isinstance(handlers, str):
				handlers = [handlers]
			with self.subTest(event=event):
				self.assertIn(ours, handlers, f"our {event} handler is not registered")
				self.assertIn(theirs, handlers, f"delivery_return's {event} handler was dropped")

	# ------------------------------------------------------------- resolver

	def test_resolve_answers_only_when_there_is_exactly_one_delivery(self):
		"""`_resolve` takes the whole row set and answers in ONE grouped query.

		A row with no note, or with more than one, is simply absent from the map —
		`_apply` reads that as `(None, None, 0.0)`. The "exactly one" rule lives in
		the `HAVING COUNT(*) = 1`, not in a per-row loop, which is also what keeps a
		twenty-line note to one query on submit and one on cancel.

		The third element is the note row's OWN qty. Count alone cannot tell a full
		delivery from a partial one, and `_apply` needs the quantity to refuse the
		partial — see `test_a_partial_delivery_leaves_the_link_blank`.
		"""
		resolve = _attr(self.backlink, "_resolve")
		self.assertEqual(resolve(["no-such-si-row"]), {})

		invoice = self._invoice()
		row = invoice.items[0].name
		note = self._note_from(invoice)
		note.insert()
		note.submit()
		self.assertEqual(
			resolve([row, "no-such-si-row"]),
			{row: (note.name, note.items[0].name, flt(note.items[0].qty))},
		)

	def test_a_partial_delivery_leaves_the_link_blank(self):
		"""🔴 COUNT IS NOT COVERAGE — the defect the escalated review caught.

		`HAVING COUNT(*) = 1` proves exactly one note row cites this invoice row. It
		says nothing about how much of it shipped. Invoice 10, deliver 3: one row, so
		on count alone `dn_detail` would name a note that moved under a third of the
		line — and `dn_detail` reads as "this line went out on that note" to a human
		and to `update_billing_status` alike.

		Asserted alongside the delivery note still being creatable, because the fix
		must refuse the LINK, not the delivery.
		"""
		invoice = self._invoice(qty=10)
		si_row = invoice.items[0].name

		note = self._note_from(invoice, qty=3)
		self.assertTrue(note.items, "make_delivery_note returned no rows")
		self.assertEqual(flt(note.items[0].qty), 3.0)
		note.insert()
		note.submit()

		link = self._link(si_row)
		self.assertFalse(link.dn_detail, "a 3-of-10 delivery claimed the whole invoice line")
		self.assertFalse(link.delivery_note, "a 3-of-10 delivery claimed the whole invoice line")

	def test_a_delivery_that_covers_the_line_does_link(self):
		"""The complement of the partial case — the qty guard must not refuse
		everything. Same shape, full quantity, link present."""
		invoice = self._invoice(qty=10)
		si_row = invoice.items[0].name

		note = self._note_from(invoice)
		note.insert()
		note.submit()

		link = self._link(si_row)
		self.assertEqual(link.delivery_note, note.name)
		self.assertEqual(link.dn_detail, note.items[0].name)

	def test_two_concurrent_submits_self_heal_to_blank(self):
		"""Read-then-write with no lock: two notes submitted at once could both see
		"exactly one" and both write. The window is small and the end state heals —
		but it is asserted rather than assumed."""
		invoice = self._invoice(qty=10)
		row = invoice.items[0].name
		first = self._note_from(invoice, qty=5)
		second = self._note_from(invoice, qty=5)
		first.insert()
		second.insert()
		first.submit()
		second.submit()

		# Whatever order the two racing writes landed in, re-running either handler
		# converges on the ambiguous answer.
		self.backlink.link_invoice_rows(frappe.get_doc("Delivery Note", first.name))
		self.assertFalse(self._link(row).dn_detail)

	# ------------------------------------------------------------- what is NOT touched

	def test_the_module_never_writes_delivered_qty_or_per_delivered(self):
		"""32.5, explicitly. `Sales Invoice Item.delivered_qty` is already maintained
		by `DeliveryNote`'s own `status_updater`, which joins on `si_detail` and
		carries its own over-delivery guard — writing it ourselves double-counts
		against that guard. And Sales Invoice has NO `per_delivered` field at all;
		`per_delivered` in `sales_invoice.py` targets the Sales Order."""
		source = _source("delivery_backlink.py")
		self.assertNotIn("delivered_qty", source)
		self.assertNotIn("per_delivered", source)

	def test_the_module_never_saves_a_submitted_parent(self):
		source = _source("delivery_backlink.py")
		self.assertNotIn(".save()", source, "saving a submitted parent to change a child row")
		self.assertIn("update_modified=False", source)

	def test_delivered_qty_is_still_whatever_erpnext_set(self):
		invoice = self._invoice(qty=10)
		row = invoice.items[0].name
		note = self._note_from(invoice, qty=10)
		note.insert()
		note.submit()

		self.assertEqual(
			flt(frappe.db.get_value("Sales Invoice Item", row, "delivered_qty")),
			10.0,
			"delivered_qty is not what ERPNext's StatusUpdater set",
		)


# ============================================================== item 33


PE_TAX_SECTIONS = ("taxes_and_charges_section", "section_break_56", "section_break_60")
PE_TAX_HIDDEN = (
	"purchase_taxes_and_charges_template",
	"apply_tax_withholding_amount",
	"tax_withholding_category",
)
PE_TAX_FIELDS = PE_TAX_SECTIONS + PE_TAX_HIDDEN + (
	"sales_taxes_and_charges_template",
	"column_break_55",
	"taxes",
	"base_total_taxes_and_charges",
	"column_break_61",
	"total_taxes_and_charges",
	"deductions_or_loss_section",
	"deductions",
)
PREPAYMENT_FLAG = "custom_prepayment_invoice"


class TestItem33PaymentEntryTaxBlock(FrappeTestCase):
	"""Hide the tax block on Payment Entry — without stranding prepayments.

	🔴 The requirement's list as written is self-defeating.
	`sales_taxes_and_charges_template` lives INSIDE `taxes_and_charges_section`, so
	hiding that section hides the template whatever its own `hidden` says — and the
	template carries `mandatory_depends_on: eval:doc.custom_prepayment_invoice`, so
	every prepayment Payment Entry becomes unsaveable with a mandatory error
	pointing at a field nobody can see. That is exactly the failure the requirement
	asks to avoid, which is why this is `depends_on`, not `hidden`.
	"""

	def tearDown(self):
		frappe.db.rollback()

	def test_every_fieldname_in_the_map_exists_on_live_meta(self):
		"""Strict, and `section_break_56` / `section_break_60` in particular — those
		are the two most likely to have been renumbered by a version bump."""
		meta = frappe.get_meta("Payment Entry")
		for fieldname in PE_TAX_FIELDS:
			with self.subTest(fieldname=fieldname):
				self.assertIsNotNone(
					meta.get_field(fieldname), f"Payment Entry.{fieldname} does not exist"
				)

	def test_no_hand_edited_field_order_has_dropped_one_of_these_fields(self):
		"""🔴 THE COLLISION THE SPEC FLAGS FOR THE GATE, AS A TEST.

		A third developer is hand-editing Payment Entry field order through
		Customize Form. This item writes only `hidden` / `depends_on`, never
		`field_order`, so there is no direct clash — but a `field_order` Property
		Setter that DROPS one of these fieldnames removes the field from the form
		entirely (recorded gotcha 70) while every assertion above still passes,
		because `hidden` and `depends_on` are perfectly set on a field nobody can
		reach. This is the only test that can see that.
		"""
		stored = frappe.db.get_value(
			"Property Setter",
			{"doc_type": "Payment Entry", "property": "field_order", "doctype_or_field": "DocType"},
			"value",
		)
		if not stored:
			self.skipTest("Payment Entry has no hand-edited field_order Property Setter")
		order = set(json.loads(stored) or [])
		for fieldname in (*PE_TAX_FIELDS, PREPAYMENT_FLAG):
			with self.subTest(fieldname=fieldname):
				self.assertIn(
					fieldname,
					order,
					f"a hand-edited field_order dropped Payment Entry.{fieldname} from the form",
				)

	def test_the_three_section_breaks_collapse_unless_it_is_a_prepayment(self):
		meta = frappe.get_meta("Payment Entry")
		for fieldname in PE_TAX_SECTIONS:
			with self.subTest(fieldname=fieldname):
				depends_on = meta.get_field(fieldname).depends_on or ""
				self.assertIn(PREPAYMENT_FLAG, depends_on, f"{fieldname} has no prepayment gate")

	def test_the_gate_is_combined_with_a_shipped_depends_on_not_stacked_twice(self):
		"""Running the step twice must not append the expression again — that is what
		"combine rather than overwrite" turns into if it is written carelessly."""
		step = _attr(form_layout, "setup_payment_entry_tax_block")
		step()
		frappe.clear_cache(doctype="Payment Entry")
		meta = frappe.get_meta("Payment Entry")
		for fieldname in PE_TAX_SECTIONS:
			with self.subTest(fieldname=fieldname):
				depends_on = meta.get_field(fieldname).depends_on or ""
				self.assertEqual(
					depends_on.count(PREPAYMENT_FLAG), 1, f"{fieldname}: {depends_on!r}"
				)

	def test_the_three_unwanted_fields_are_hidden_in_both_states(self):
		meta = frappe.get_meta("Payment Entry")
		for fieldname in PE_TAX_HIDDEN:
			with self.subTest(fieldname=fieldname):
				self.assertTrue(meta.get_field(fieldname).hidden, f"{fieldname} is still visible")

	def test_the_sales_template_stays_visible(self):
		"""It is reachable exactly when the prepayment flag is ticked, which is what
		the requirement asks for — and what keeps the mandatory rule satisfiable."""
		self.assertFalse(
			frappe.get_meta("Payment Entry").get_field("sales_taxes_and_charges_template").hidden
		)

	def test_deductions_survive_untouched(self):
		"""`deductions_or_loss_section` is itself a Section Break, so the hidden span
		ends there — the "hiding a section hides everything inside it" rule works FOR
		us here. Neither field may carry a gate of ours."""
		meta = frappe.get_meta("Payment Entry")
		for fieldname in ("deductions_or_loss_section", "deductions"):
			with self.subTest(fieldname=fieldname):
				field = meta.get_field(fieldname)
				self.assertFalse(field.hidden, f"{fieldname} was hidden")
				self.assertNotIn(PREPAYMENT_FLAG, field.depends_on or "")

	def test_the_escape_hatch_is_reachable(self):
		"""If `custom_prepayment_invoice` is itself hidden the whole design is
		unreachable and this item cannot ship as specced."""
		field = frappe.get_meta("Payment Entry").get_field(PREPAYMENT_FLAG)
		self.assertIsNotNone(field, f"Payment Entry.{PREPAYMENT_FLAG} does not exist")
		self.assertFalse(field.hidden, "the prepayment flag is hidden — the escape hatch is dead")

	def test_the_mandatory_rule_is_left_exactly_as_it_was(self):
		"""Gate Q5: `zatca_vat_report` IS installed and WILL revert anything we
		blank. `mandatory_depends_on` is ZATCA-adjacent and belongs to a client
		decision, not this change.

		⚠️ SCOPED TO WHAT THIS CHANGE OWNS, because the earlier form was
		self-contradicting: it asserted the rule EXISTS and that no Property Setter
		provides it, when a Property Setter is the only mechanism that can put a
		`mandatory_depends_on` on a standard field. Whoever wrote that row — a
		Customize Form save, or `zatca_vat_report` — the question this item has to
		answer is "does `setup_payment_entry_tax_block` touch it", and the way to
		ask that is to run the step and compare. Idempotence is the assertion.
		"""
		self.assertIn(
			"zatca_vat_report",
			frappe.get_installed_apps(),
			"the gate measured zatca_vat_report as INSTALLED — this premise changed",
		)
		field = frappe.get_meta("Payment Entry").get_field("sales_taxes_and_charges_template")
		self.assertIn(PREPAYMENT_FLAG, field.mandatory_depends_on or "",
		              "the prepayment mandatory rule was blanked")

		before = _property_setters(
			"Payment Entry", "sales_taxes_and_charges_template", "mandatory_depends_on"
		)
		_attr(form_layout, "setup_payment_entry_tax_block")()
		after = _property_setters(
			"Payment Entry", "sales_taxes_and_charges_template", "mandatory_depends_on"
		)
		self.assertEqual(
			before, after, "this item wrote or changed a mandatory_depends_on Property Setter"
		)

	def test_a_prepayment_entry_with_a_template_saves(self):
		entry = _prepayment_entry()
		if entry is None:
			self.skipTest("site lacks the company/party/accounts to build a Payment Entry")
		template = _first("Sales Taxes and Charges Template", {"company": entry.company})
		if not template:
			self.skipTest("no sales tax template on this site")
		entry.set(PREPAYMENT_FLAG, 1)
		entry.sales_taxes_and_charges_template = template
		entry.insert()  # must not raise

	def test_the_mandatory_rule_is_a_FORM_gate_and_nothing_server_side_enforces_it(self):
		"""🔴 INVERTED, AND THE INVERSION IS THE POINT — it corrects item 33's own
		safety story rather than decorating it.

		This asserted `frappe.MandatoryError` on an insert with the flag ticked and
		no template. That can never fire: `mandatory_depends_on` is evaluated
		**client-side only** in v15. `frappe/public/js/frappe/form/layout.js` sets
		`reqd` from it in the browser, and
		`frappe/model/base_document.py:738 _get_missing_mandatory_fields()` reads
		only `reqd` — the string does not appear anywhere in frappe's Python
		validation path at all (checked across the whole repo, not from memory).

		So what item 33 actually ships is: the section is un-collapsed by the flag,
		the operator sees the template field, and the BROWSER makes it required.
		That is all the framework offers, and it is worth saying plainly — the
		"escape hatch" argument rests on a client-side mechanism, and the flag is
		ticked on 0 of 2,877 Payment Entries, so nothing server-side proves it.
		What this test can pin is that the metadata rule is intact and that the
		server does NOT refuse, so a REST or import caller is not silently blocked.
		"""
		field = frappe.get_meta("Payment Entry").get_field("sales_taxes_and_charges_template")
		self.assertIn(
			PREPAYMENT_FLAG,
			field.mandatory_depends_on or "",
			"the form gate is gone — nothing asks for a template at all now",
		)
		self.assertFalse(cint(field.reqd), "the field became unconditionally mandatory")

		entry = _prepayment_entry()
		if entry is None:
			self.skipTest("site lacks the company/party/accounts to build a Payment Entry")
		entry.set(PREPAYMENT_FLAG, 1)
		entry.sales_taxes_and_charges_template = None
		entry.insert()  # the server does not enforce it, and must not start silently doing so

	def test_the_step_is_registered(self):
		self.assertIn("setup_payment_entry_tax_block", setup.PROVISIONING_STEPS)


def _prepayment_entry():
	"""A minimal Receive Payment Entry, or None when the site cannot make one."""
	company = _first("Company")
	customer = _first("Customer")
	if not (company and customer):
		return None
	paid_to = frappe.db.get_value(
		"Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
	) or frappe.db.get_value(
		"Account", {"company": company, "account_type": "Cash", "is_group": 0}, "name"
	)
	receivable = frappe.db.get_value(
		"Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name"
	)
	if not (paid_to and receivable):
		return None

	entry = frappe.new_doc("Payment Entry")
	entry.payment_type = "Receive"
	entry.company = company
	entry.party_type = "Customer"
	entry.party = customer
	entry.paid_from = receivable
	entry.paid_to = paid_to
	entry.paid_amount = 100
	entry.received_amount = 100
	entry.posting_date = today()
	entry.reference_no = "BATCH3"
	entry.reference_date = today()
	return entry


# ============================================================== item 35


class TestItem35ListOpensOnTheCurrentFiscalYear(FrappeTestCase):
	"""A FILTER default, never a field default."""

	def setUp(self):
		self.module = _module("list_defaults")
		self.restore = []

	def tearDown(self):
		for restore in reversed(self.restore):
			restore()
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_the_resolver_returns_the_year_covering_today(self):
		resolver = _attr(self.module, "current_fiscal_year")
		self.assertEqual(resolver(), fiscal_year.resolve(today()))

	def test_the_resolver_rolls_with_the_date(self):
		"""It has to roll to 2027 on its own — reusing `fiscal_year.resolve` is what
		buys that, and what inherits "never raise, return empty when no year covers
		today"."""
		resolver = _attr(self.module, "current_fiscal_year")
		later = frappe.get_all(
			"Fiscal Year",
			filters={"disabled": 0, "year_start_date": [">", today()]},
			fields=["name", "year_start_date"],
			order_by="year_start_date asc",
			limit=1,
		)
		if not later:
			self.skipTest("no future Fiscal Year on this site to roll into")

		target = later[0]
		self.restore.append(
			_patch(self.module, "today", lambda: str(getdate(target.year_start_date)))
			if hasattr(self.module, "today")
			else _patch(frappe.utils, "today", lambda: str(getdate(target.year_start_date)))
		)
		self.assertEqual(resolver(), target.name)

	def test_an_unresolvable_year_returns_empty_and_never_raises(self):
		resolver = _attr(self.module, "current_fiscal_year")
		self.restore.append(_patch(fiscal_year, "resolve", lambda *a, **k: ""))
		self.assertEqual(resolver(), "")

	def test_boot_carries_the_year_for_every_kind_of_user(self):
		"""🔴 The key has to be set ABOVE the `Administrator` / `Guest` and
		bypass-role early returns, or a manager's lists never get the filter."""
		expected = _attr(self.module, "current_fiscal_year")()
		branch = _ensure_user(BRANCH_USER, ["Branch User"])
		manager = _ensure_user(MANAGER_USER, ["System Manager"])

		for user in ("Administrator", manager, branch):
			with self.subTest(user=user):
				frappe.set_user(user)
				bootinfo = frappe._dict()
				boot.boot_session(bootinfo)
				self.assertEqual(bootinfo.get("yht_current_fiscal_year"), expected)

	def test_the_list_js_is_registered_for_all_eight_doctypes(self):
		"""🔴 `doctype_list_js`, not `app_include_js`. ERPNext's list JS assigns
		`frappe.listview_settings["X"]` wholesale and the list bundle loads AFTER
		`app_include_js`; `frappe/desk/form/meta.py` concatenates the
		`doctype_list_js` hook file after ERPNext's, so a merge from there survives.
		"""
		registered = frappe.get_hooks("doctype_list_js", app_name="yht_custom") or {}
		for doctype in fiscal_year.DATE_FIELD:
			with self.subTest(doctype=doctype):
				entry = registered.get(doctype)
				entries = entry if isinstance(entry, list) else [entry] if entry else []
				self.assertTrue(
					any("list_defaults.js" in str(path) for path in entries),
					f"{doctype}: list_defaults.js is not registered under doctype_list_js",
				)

	def test_the_js_merges_and_never_assigns(self):
		source = _source("public/js/list_defaults.js")
		self.assertIn("frappe.boot.yht_current_fiscal_year", source)
		self.assertIn(fiscal_year.FIELDNAME, source)
		clobber = re.search(r"frappe\.listview_settings\[[^\]]+\]\s*=\s*\{", source)
		self.assertIsNone(
			clobber, "the JS ASSIGNS frappe.listview_settings — it must merge, or ERPNext's is lost"
		)

	def test_the_js_sets_no_filter_when_boot_is_empty(self):
		source = _source("public/js/list_defaults.js")
		self.assertRegex(
			source,
			r"if\s*\(\s*!?\s*frappe\.boot\.yht_current_fiscal_year",
			"the JS does not guard on an empty fiscal year",
		)

	def test_the_field_still_carries_no_default_anywhere(self):
		"""🔴 35.4, THE ONE THAT MATTERS. A fixed default on the FIELD is what left
		731 Sales Invoices stamped FY 2026 while dated from 2024-08-01. This item is
		a LIST-FILTER default only."""
		for doctype in fiscal_year.DATE_FIELD:
			with self.subTest(doctype=doctype):
				field = frappe.get_meta(doctype).get_field(fiscal_year.FIELDNAME)
				self.assertIsNotNone(field, f"{doctype}: {fiscal_year.FIELDNAME} is missing")
				self.assertFalse(field.default, f"{doctype}: the field grew a default")
				self.assertFalse(
					frappe.db.get_value(
						"Custom Field",
						{"dt": doctype, "fieldname": fiscal_year.FIELDNAME},
						"default",
					),
					f"{doctype}: the Custom Field record carries a default",
				)
				self.assertFalse(
					_property_setters(doctype, fiscal_year.FIELDNAME, "default"),
					f"{doctype}: a Property Setter gives the field a default",
				)

	def test_the_field_stays_read_only(self):
		for doctype in fiscal_year.DATE_FIELD:
			with self.subTest(doctype=doctype):
				self.assertEqual(
					cint(frappe.get_meta(doctype).get_field(fiscal_year.FIELDNAME).read_only), 1
				)


# ============================================================== item 36


RETURN_SPLIT_DOCTYPES = ("Sales Invoice", "Delivery Note", "Purchase Invoice", "Purchase Receipt")


class TestItem36ReturnSplitFilter(FrappeTestCase):
	"""GATE DECISION Q9 — the CHEAP option, not the Select.

	`in_standard_filter = 1` on the EXISTING `is_return` Check on four doctypes.
	No new Custom Field, no derived `custom_document_kind` column, no 8,603-row
	backfill patch. Rationale: it is literally the control the client pointed at
	(`Is Expense Invoice`), and a Custom Field that is later withdrawn leaves its
	column and its data behind.

    Known limitation, ACCEPTED: a tick shows returns only; unticked shows
    everything, so it cannot express "forward only". If the client rejects that on
    yht-test, the Select is a follow-up — not a rebuild.
	"""

	def tearDown(self):
		frappe.db.rollback()

	def test_is_return_is_a_standard_filter_on_all_four_lists(self):
		for doctype in RETURN_SPLIT_DOCTYPES:
			with self.subTest(doctype=doctype):
				field = frappe.get_meta(doctype).get_field("is_return")
				self.assertIsNotNone(field, f"{doctype}.is_return does not exist")
				self.assertEqual(field.fieldtype, "Check")
				self.assertEqual(
					cint(field.in_standard_filter), 1, f"{doctype}: is_return is not in the filter row"
				)

	def test_the_property_setter_is_field_level(self):
		for doctype in RETURN_SPLIT_DOCTYPES:
			with self.subTest(doctype=doctype):
				rows = _property_setters(doctype, "is_return", "in_standard_filter")
				self.assertTrue(rows, f"{doctype}: no in_standard_filter Property Setter")
				self.assertEqual(rows[0]["doctype_or_field"], "DocField")
				self.assertEqual(str(rows[0]["value"]), "1")

	def test_is_return_is_visible_because_a_hidden_field_cannot_be_filtered_on(self):
		for doctype in RETURN_SPLIT_DOCTYPES:
			with self.subTest(doctype=doctype):
				self.assertFalse(frappe.get_meta(doctype).get_field("is_return").hidden)

	def test_unticked_still_shows_everything(self):
		"""`get_standard_filters()` skips a field whose value is falsy, so an
		unticked box applies no filter — which is what makes "blank shows both"
		work. A `default = "1"` would open every list on returns only."""
		for doctype in RETURN_SPLIT_DOCTYPES:
			with self.subTest(doctype=doctype):
				field = frappe.get_meta(doctype).get_field("is_return")
				self.assertIn(str(field.default or "0"), ("0", "None", ""))
				self.assertFalse(
					_property_setters(doctype, "is_return", "default"),
					f"{doctype}: this item wrote a default onto is_return",
				)

	# ------------------------------------- the withdrawn design must be ABSENT

	def test_no_custom_document_kind_field_was_created(self):
		"""The gate DROPPED the Select. A coder reading the spec body alone would
		build it — and a Custom Field that is later withdrawn leaves its column and
		its data behind (recorded gotcha 22), so this is not a harmless extra."""
		for doctype in RETURN_SPLIT_DOCTYPES:
			with self.subTest(doctype=doctype):
				self.assertIsNone(
					frappe.get_meta(doctype).get_field("custom_document_kind"),
					f"{doctype}: the withdrawn custom_document_kind Select was built",
				)
				self.assertFalse(
					frappe.db.exists("Custom Field", f"{doctype}-custom_document_kind")
				)

	def test_no_document_kind_hook_is_registered(self):
		for doctype in RETURN_SPLIT_DOCTYPES:
			handlers = frappe.get_hooks("doc_events").get(doctype, {}).get("validate") or []
			if isinstance(handlers, str):
				handlers = [handlers]
			with self.subTest(doctype=doctype):
				self.assertNotIn("yht_custom.list_defaults.set_document_kind", handlers)

	def test_no_backfill_patch_was_added(self):
		self.assertFalse(
			os.path.exists(os.path.join(APP_ROOT, "patches", "backfill_document_kind.py")),
			"the withdrawn backfill patch was written",
		)
		self.assertNotIn("backfill_document_kind", _source("patches.txt"))

	def test_no_document_kind_fixture_entries(self):
		names = set()
		for entry in frappe.get_hooks("fixtures", app_name="yht_custom") or []:
			if not isinstance(entry, dict) or entry.get("dt") != "Custom Field":
				continue
			for clause in entry.get("filters") or []:
				if len(clause) == 3 and clause[1] == "in":
					names.update(clause[2])
		self.assertFalse(
			[name for name in names if "custom_document_kind" in name],
			"a fixture entry for the withdrawn field",
		)

	def test_the_step_is_registered_and_the_dropped_one_is_not(self):
		self.assertIn("setup_return_split_filter", setup.PROVISIONING_STEPS)
		self.assertNotIn("ensure_document_kind_fields", setup.PROVISIONING_STEPS)

	def test_running_the_step_twice_writes_nothing_new(self):
		step = _attr(form_layout, "setup_return_split_filter")
		before = frappe.db.count("Property Setter")
		step()
		self.assertEqual(frappe.db.count("Property Setter"), before)


# ============================================================== wiring


class TestBatch3Wiring(FrappeTestCase):
	"""Every item is its own provisioning step, so one failure cannot hide another."""

	#: `setup_title_as_voucher_no` is deliberately ABSENT — item 24's mechanism was
	#: withdrawn (it empties every transaction list) and the step is unregistered.
	#: `test_the_withdrawn_item_24_step_is_not_wired` asserts that below, so dropping
	#: it from this tuple loses no coverage.
	NEW_STEPS = (
		"setup_update_stock_default",
		"setup_payment_entry_tax_block",
		"setup_return_split_filter",
		"ensure_other_remarks_fields",
	)

	def test_the_withdrawn_item_24_step_is_not_wired(self):
		"""Item 24's mechanism empties every transaction list. It must stay out of
		PROVISIONING_STEPS, and calling it directly must refuse — unregistered is one
		careless `bench execute` away from being run on a client site anyway."""
		self.assertNotIn("setup_title_as_voucher_no", setup.PROVISIONING_STEPS)
		self.assertRaises(frappe.ValidationError, form_layout.setup_title_as_voucher_no)

	def test_each_item_is_its_own_step(self):
		for step in self.NEW_STEPS:
			with self.subTest(step=step):
				self.assertIn(step, setup.PROVISIONING_STEPS)

	def test_every_step_resolves_to_something_callable(self):
		"""`after_migrate` does `globals().get(step) or _imported(step)`. A step in
		the tuple with no entry in either raises KeyError and takes the whole
		migrate's remaining steps with it."""
		import yht_custom.setup as setup_module

		for step in self.NEW_STEPS:
			with self.subTest(step=step):
				func = getattr(setup_module, step, None)
				if func is None:
					try:
						func = setup_module._imported(step)
					except KeyError:
						self.fail(f"{step} is a declared step but resolves to nothing")
				self.assertTrue(callable(func))

	def test_the_new_steps_run_after_the_existing_form_layout_step(self):
		steps = list(setup.PROVISIONING_STEPS)
		anchor = steps.index("setup_form_layout")
		for step in self.NEW_STEPS:
			if step in steps:
				with self.subTest(step=step):
					self.assertGreater(steps.index(step), anchor)

	def test_the_new_patch_is_registered_once(self):
		lines = [line.strip() for line in _source("patches.txt").splitlines() if line.strip()]
		self.assertEqual(
			lines.count("yht_custom.patches.purge_orphan_global_search"),
			1,
			"the purge patch is missing or registered twice",
		)

	def test_after_migrate_still_reports_every_failure_separately(self):
		"""The whole reason each item is its own step, asserted on the CONTRACT.

		🔴 This deliberately does NOT call `setup.after_migrate()`.
		`after_migrate` runs `frappe.db.commit()` after every step, and a commit
		inside a test is permanent — `tearDown`'s rollback cannot undo it, and
		`FrappeTestCase` rolls back once per CLASS anyway. Running thirty
		provisioning steps against a copy of the client database to prove a
		try/except exists is exactly the shape that appended a marker naming series
		to the live picker on every site the suite had touched.

		What actually has to hold is that each new step is wrapped individually, so
		one failure cannot hide another. That is a property of the loop, and the
		loop is read here rather than executed.
		"""
		loop = inspect.getsource(setup.after_migrate)
		self.assertIn("for step in PROVISIONING_STEPS", loop, "the per-step loop is gone")
		self.assertIn("except", loop, "a failing step now aborts the whole after_migrate")
		self.assertIn("failures", loop, "failures are no longer collected per step")
		# The commit belongs INSIDE the loop: one step's success must not be rolled
		# back by the next step's failure.
		body = loop.split("for step in PROVISIONING_STEPS", 1)[1]
		self.assertIn("frappe.db.commit()", body)
		self.assertIn("frappe.db.rollback()", body)

	def test_no_new_step_was_bolted_into_setup_form_layout(self):
		"""Each item is registered as its own `PROVISIONING_STEPS` entry rather than
		called from inside `setup_form_layout` — otherwise one item's exception
		takes the other five down with it and `after_migrate` reports one failure
		where there were two."""
		body = inspect.getsource(form_layout.setup_form_layout)
		for step in ("setup_title_as_voucher_no", "setup_update_stock_default",
		             "setup_payment_entry_tax_block", "setup_return_split_filter"):
			with self.subTest(step=step):
				self.assertNotIn(
					step, body, f"{step} is called from setup_form_layout instead of being its own step"
				)
