# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Client sheet (Openarabia Team) — batch 1: items 3, 4, 5, 10, 11.

Item 2 was already shipped. Item 12 is Out Of Scope on the sheet itself.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from yht_custom import rate_lock
from yht_custom.form_layout import GROUP_BEFORE, SORT_BY_NAME, _TAXES_BLOCK
from yht_custom.workspace_shortcuts import LABEL, NEW_SHORTCUTS


class TestItem3TaxesHidden(FrappeTestCase):
	"""Hide the Taxes and Charges block on Sales Invoice."""

	def test_the_whole_block_is_hidden(self):
		meta = frappe.get_meta("Sales Invoice")
		for fieldname in _TAXES_BLOCK:
			with self.subTest(fieldname=fieldname):
				field = meta.get_field(fieldname)
				self.assertTrue(field, f"Sales Invoice has no {fieldname}")
				self.assertTrue(field.hidden, f"{fieldname} is still visible")

	def test_the_computed_vat_is_NOT_hidden(self):
		"""The client asked to hide the block, not the tax.

		`total_taxes_and_charges` lives in a different section and must survive, or
		the invoice stops showing the VAT it charges.
		"""
		meta = frappe.get_meta("Sales Invoice")
		for fieldname in ("total_taxes_and_charges", "base_total_taxes_and_charges",
		                  "grand_total", "rounded_total"):
			with self.subTest(fieldname=fieldname):
				self.assertFalse(meta.get_field(fieldname).hidden, f"{fieldname} was hidden")

	def test_the_default_tax_template_still_applies(self):
		"""Hiding the picker is only safe because the template is a company default."""
		company = frappe.defaults.get_global_default("company")
		default = frappe.db.get_value(
			"Sales Taxes and Charges Template", {"company": company, "is_default": 1}, "name"
		)
		self.assertTrue(default, "no default sales tax template — hiding the picker would strand VAT")


class TestItem4SortOrder(FrappeTestCase):
	"""List and report views sort by document ID, newest first."""

	def test_every_transaction_list_sorts_by_name(self):
		for doctype in SORT_BY_NAME:
			with self.subTest(doctype=doctype):
				meta = frappe.get_meta(doctype)
				self.assertEqual(meta.sort_field, "name")
				self.assertEqual((meta.sort_order or "").upper(), "DESC")

	def test_the_property_setters_are_doctype_level(self):
		"""🔴 The bug this test exists for.

		`frappe.make_property_setter` defaults `doctype_or_field` to "DocField".
		Twelve rows inserted cleanly as DocField with a NULL field_name, migrate
		reported success, and every list stayed on `modified DESC`. Meta only reads
		DocType-level rows for these two properties.
		"""
		rows = frappe.get_all(
			"Property Setter",
			filters={"property": ["in", ["sort_field", "sort_order"]]},
			fields=["doc_type", "property", "doctype_or_field"],
		)
		self.assertTrue(rows)
		for row in rows:
			with self.subTest(doctype=row.doc_type, prop=row.property):
				self.assertEqual(row.doctype_or_field, "DocType")

	def test_sorting_by_name_really_orders_by_year(self):
		"""The names carry the year, which is what makes ID-sort a fiscal-year sort."""
		names = frappe.get_all("Sales Invoice", limit=5, pluck="name")
		if len(names) < 2:
			self.skipTest("not enough invoices")
		self.assertEqual(names, sorted(names, reverse=True))


class TestItem10FormOrder(FrappeTestCase):
	"""Store sits immediately above the item table."""

	def test_the_trio_sits_contiguously_above_the_item_table(self):
		"""update stock · price list · store, in that order, then the items.

		Asserting CONTIGUITY rather than "each is somewhere before" is the point:
		the first cut satisfied "before" while leaving another field wedged between
		them, and on Sales Invoice it pushed update_stock past the items table.
		"""
		for doctype, (group, anchor) in GROUP_BEFORE.items():
			with self.subTest(doctype=doctype):
				order = [f.fieldname for f in frappe.get_meta(doctype).fields]
				present = [f for f in group if f in order]
				self.assertTrue(present, f"{doctype}: none of {group} exists")
				self.assertIn(anchor, order)

				at = order.index(anchor)
				self.assertEqual(
					order[at - len(present) : at],
					present,
					f"{doctype}: {present} is not contiguous immediately before {anchor}",
				)

	def test_the_layout_is_stable_across_migrations(self):
		"""The oscillation bug: two rules rewriting field_order, each undoing the
		other. Running the step twice must be a no-op the second time."""
		from yht_custom import form_layout

		before = {
			dt: [f.fieldname for f in frappe.get_meta(dt).fields] for dt in GROUP_BEFORE
		}
		form_layout._group_before()
		frappe.clear_cache()
		after = {
			dt: [f.fieldname for f in frappe.get_meta(dt).fields] for dt in GROUP_BEFORE
		}
		for doctype in GROUP_BEFORE:
			with self.subTest(doctype=doctype):
				self.assertEqual(before[doctype], after[doctype])


class TestItem11NewShortcuts(FrappeTestCase):
	"""A direct New button on every transaction module."""

	def test_each_workspace_has_its_new_shortcuts(self):
		for workspace, doctypes in NEW_SHORTCUTS.items():
			if not frappe.db.exists("Workspace", workspace):
				self.fail(f"workspace {workspace} does not exist — check the name")
			doc = frappe.get_doc("Workspace", workspace)
			labels = {row.label for row in doc.shortcuts if row.doc_view == "New"}
			for doctype in doctypes:
				with self.subTest(workspace=workspace, doctype=doctype):
					self.assertIn(LABEL.format(doctype), labels)

	def test_every_new_shortcut_is_also_in_the_layout(self):
		"""🔴 A shortcut is TWO writes. The `content` JSON references it BY LABEL;
		without that block the shortcut exists and renders nowhere — the same trap
		that left dead 'Record Expenses' shortcuts after the Step 1 strip.
		"""
		for workspace in NEW_SHORTCUTS:
			if not frappe.db.exists("Workspace", workspace):
				continue
			doc = frappe.get_doc("Workspace", workspace)
			content = json.loads(doc.content or "[]")
			in_layout = {
				(block.get("data") or {}).get("shortcut_name")
				for block in content
				if isinstance(block, dict) and block.get("type") == "shortcut"
			}
			for row in doc.shortcuts:
				if row.doc_view != "New":
					continue
				with self.subTest(workspace=workspace, label=row.label):
					self.assertIn(row.label, in_layout)

	def test_the_shortcuts_point_at_doctypes_that_exist(self):
		for workspace, doctypes in NEW_SHORTCUTS.items():
			for doctype in doctypes:
				with self.subTest(doctype=doctype):
					self.assertTrue(frappe.db.exists("DocType", doctype))


class TestItem5RateLock(FrappeTestCase):
	"""A rate fetched from a source document is not editable."""

	def _invoice_row_from_source(self):
		row = frappe.db.sql(
			"""SELECT sii.parent, sii.name, sii.rate, sii.dn_detail, sii.so_detail
			   FROM `tabSales Invoice Item` sii
			   INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
			   WHERE si.docstatus = 1 AND si.is_return = 0
			     AND (sii.dn_detail IS NOT NULL AND sii.dn_detail != '')
			   LIMIT 1""",
			as_dict=True,
		)
		return row[0] if row else None

	def test_a_matching_rate_passes(self):
		source = self._invoice_row_from_source()
		if not source:
			self.skipTest("no invoice row fetched from a delivery note")

		doc = frappe.get_doc("Sales Invoice", source.parent)
		# Untouched — the rate already equals its source, so this must not raise.
		rate_lock.enforce_fetched_rate(doc)

	def test_an_edited_rate_is_rejected(self):
		source = self._invoice_row_from_source()
		if not source:
			self.skipTest("no invoice row fetched from a delivery note")

		doc = frappe.get_doc("Sales Invoice", source.parent)
		frappe.set_user("Administrator")
		for row in doc.items:
			if row.dn_detail:
				row.rate = flt(row.rate) + 25
				break

		# Administrator bypasses, so assert as a user who does not.
		doc.flags.yht_force_check = True
		from yht_custom import sales_flow

		original = sales_flow._may_bypass
		sales_flow._may_bypass = lambda user=None: False
		rate_lock._may_bypass = lambda user=None: False
		try:
			with self.assertRaises(frappe.ValidationError):
				rate_lock.enforce_fetched_rate(doc)
		finally:
			sales_flow._may_bypass = original
			rate_lock._may_bypass = original

	def test_a_credit_note_may_restate_the_rate(self):
		"""A return mirrors the original on purpose."""
		doc = frappe.new_doc("Sales Invoice")
		doc.is_return = 1
		doc.append("items", {"item_code": "x", "rate": 999, "dn_detail": "does-not-exist"})
		rate_lock.enforce_fetched_rate(doc)  # must not raise

	def test_a_hand_added_row_is_untouched(self):
		"""Rows with no source document stay freely editable."""
		doc = frappe.new_doc("Sales Invoice")
		doc.append("items", {"item_code": "x", "rate": 123})
		rate_lock.enforce_fetched_rate(doc)  # must not raise

	def test_the_hook_is_registered(self):
		handlers = frappe.get_hooks("doc_events").get("Sales Invoice", {}).get("validate") or []
		if isinstance(handlers, str):
			handlers = [handlers]
		self.assertIn("yht_custom.rate_lock.enforce_fetched_rate", handlers)
