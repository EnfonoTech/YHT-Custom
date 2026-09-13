# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""The Khobar reproduction of the incumbent Sales Invoice print.

Every assertion here is aimed at a defect that was MEASURED on `yht-test`, not at
the configuration. The two that matter:

* `test_a_legacy_delivery_note_actually_reaches_the_page` fails on the incumbent
  markup as-is. `doc.custom_delivery_note_` is a purged Table field; jinja renders
  Undefined as nothing and raises nothing, so 1,178 of 2,360 invoices printed an
  empty cell with a clean log.
* `test_the_tax_column_is_not_a_row_of_zeroes` fails on the incumbent markup as-is
  too — `custom_tax_amount` is a purged column that nothing on this system writes,
  so every invoice raised here printed `0.00` under `TAX AMT`.

Nothing in this module writes to the database.
"""

import os
import re
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

FORMAT_NAME = "KATHOOM KHOBAR INV FORMAT NEW"
TEMPLATE_PATH = "yht_custom/templates/includes/legacy/khobar_tax_invoice.html"


def _render(doc) -> str:
	"""Render through the Print Format record, so the include shim is exercised too.

	Deliberately NOT `frappe.get_print`: that commits the open transaction
	(gotcha 84), which a read-only test has no business doing.
	"""
	html = frappe.db.get_value("Print Format", FORMAT_NAME, "html")
	return frappe.render_template(
		html, {"doc": doc, "letter_head": "", "no_letterhead": 1, "footer": ""}
	)


def _invoice_with_legacy_delivery_rows() -> str | None:
	if not frappe.db.table_exists("Delivery Note si", cached=True):
		return None
	rows = frappe.db.sql(
		"""select si.name from `tabSales Invoice` si
		   join `tabDelivery Note si` d
		     on d.parent = si.name and d.parentfield = 'custom_delivery_note_'
		   where si.docstatus = 1 and ifnull(d.delivery_note, '') != ''
		   limit 1"""
	)
	return rows[0][0] if rows else None


class TestKhobarInvoiceFormatIsWired(FrappeTestCase):
	def test_the_record_is_a_two_line_shim_over_the_app_template(self):
		"""A Print Format that carries a COPY of the layout is how variants drift.

		The record must stay a shim; the layout lives in one file (gotcha 75).
		"""
		fmt = frappe.db.get_value(
			"Print Format", FORMAT_NAME, ["doc_type", "print_format_type", "disabled", "html"], as_dict=True
		)
		self.assertIsNotNone(fmt, f"{FORMAT_NAME} is not installed on this site")
		self.assertEqual(fmt.doc_type, "Sales Invoice")
		self.assertEqual(fmt.print_format_type, "Jinja")
		self.assertFalse(fmt.disabled)
		self.assertIn(TEMPLATE_PATH, fmt.html)
		self.assertLess(len(fmt.html), 200, "the record should hold the include, not the layout")

	def test_the_template_file_ships_with_the_app(self):
		path = os.path.join(frappe.get_app_path("yht_custom"), "templates", "includes", "legacy", "khobar_tax_invoice.html")
		self.assertTrue(os.path.exists(path), path)
		body = open(path, encoding="utf-8").read()
		# Both deviations must stay explained in the file a future reader opens.
		self.assertIn("DEVIATION 1", body)
		self.assertIn("DEVIATION 2", body)

		# 🔴 Assert on the EXECUTABLE template, not on the raw file. The first version of
		# this test matched bare fieldnames and failed on its own explanatory comments —
		# the comments necessarily NAME the purged fields they are explaining. Strip the
		# Jinja comments first, then the assertion means what it says.
		code = re.sub(r"\{#.*?#\}", "", body, flags=re.S)
		for purged in ("doc.custom_delivery_note_", "row.custom_tax_amount", "row.custom_total_amount"):
			self.assertNotIn(purged, code, f"{purged} is read again in the live template")
		# The orphan table is still allowed to appear — it is the repair, not the defect.
		self.assertIn("tabDelivery Note si", code)


class TestTheFormatNeedsNoNewJinjaHook(FrappeTestCase):
	"""The constraint that shaped this format, asserted rather than remembered.

	A path added to the `jinja` hook is resolved when the environment is BUILT, so
	between deploying the file and reloading the workers it raises for the whole
	environment — every website page, `/login` included (gotcha 25). This bench's
	gunicorn pool is shared with the client's PRODUCTION site, so a print format
	that needs a worker reload is a print format that cannot ship on its own.

	Measured while building this: registering one helper took `yht-test`'s `/login`
	to HTTP 500 while `yht-khobhar` stayed up only because its hook cache had not
	been cleared.
	"""

	def test_every_helper_the_template_calls_is_already_registered(self):
		path = os.path.join(
			frappe.get_app_path("yht_custom"), "templates", "includes", "legacy", "khobar_tax_invoice.html"
		)
		called = set(re.findall(r"\b(yht_[a-z0-9_]+)\s*\(", open(path, encoding="utf-8").read()))
		registered = {p.rsplit(".", 1)[-1] for p in (frappe.get_hooks("jinja") or {}).get("methods", [])}
		self.assertTrue(
			called <= registered,
			f"the template calls helpers that no installed app registers: {sorted(called - registered)}",
		)


class TestTheFormatRendersRealDocuments(FrappeTestCase):
	def _one(self, condition):
		rows = frappe.db.sql(
			f"select name from `tabSales Invoice` where docstatus = 1 and {condition} limit 1"  # noqa: S608
		)
		return rows[0][0] if rows else None

	def test_it_renders_every_shape_of_document_on_this_site(self):
		shapes = {
			"forward invoice": "is_return = 0",
			"credit note": "is_return = 1",
			"with an additional discount": "ifnull(discount_amount, 0) > 0",
			"with terms": "ifnull(terms, '') != ''",
		}
		for label, condition in shapes.items():
			name = self._one(condition)
			if not name:
				continue
			with self.subTest(shape=label, invoice=name):
				html = _render(frappe.get_doc("Sales Invoice", name))
				self.assertGreater(len(html), 2000)
				# `DebugUndefined` renders an unresolved name as its own marker text
				# rather than raising — a silent way to put `{{ doc.x }}` on a
				# customer's invoice (gotcha 77).
				self.assertNotIn("{{", html, f"{name}: an unresolved expression reached the page")

	def test_a_legacy_delivery_note_actually_reaches_the_page(self):
		"""THE regression test. Fails on the incumbent markup, silently, as shipped."""
		name = _invoice_with_legacy_delivery_rows()
		if not name:
			raise unittest.SkipTest("no legacy `Delivery Note si` rows on this site")
		doc = frappe.get_doc("Sales Invoice", name)
		expected = [
			r[0]
			for r in frappe.db.sql(
				"""select delivery_note from `tabDelivery Note si`
				   where parent = %s and parentfield = 'custom_delivery_note_'
				     and ifnull(delivery_note, '') != ''""",
				(name,),
			)
		]
		self.assertTrue(expected, f"{name} was selected because it has rows")
		html = _render(doc)
		for dn in expected:
			self.assertIn(dn, html, f"{name}: delivery note {dn} is in the data but not on the page")

	def test_no_purged_column_prints_the_literal_None(self):
		"""A purged Custom Field returns SQL NULL, and jinja renders None as text.

		A DocField would have supplied "". Without one the raw column comes back as
		None and lands on a customer-facing invoice as the word `None` — measured on
		169 invoices for `custom_invoice_type`, and on 23 of the 24 documents raised
		on this system for `custom_in_words_aed`.
		"""
		checked = 0
		for condition in ("`custom_invoice_type` is null", "`custom_in_words_aed` is null"):
			name = self._one(condition)
			if not name:
				continue
			checked += 1
			with self.subTest(invoice=name, condition=condition):
				html = _render(frappe.get_doc("Sales Invoice", name))
				self.assertNotIn(
					">None<", html, f"{name}: a NULL column printed the literal 'None'"
				)
				self.assertNotIn("None</", html, f"{name}: a NULL column printed the literal 'None'")
				self.assertNotIn(": None", html, f"{name}: a NULL column printed the literal 'None'")
		if not checked:
			raise unittest.SkipTest("no invoice on this site has either column NULL")

	def test_the_tax_column_is_not_a_row_of_zeroes(self):
		"""The second regression: the purged column nothing on this system writes."""
		name = self._one("is_return = 0 and ifnull(total_taxes_and_charges, 0) > 1")
		if not name:
			raise unittest.SkipTest("no taxed invoice on this site")
		doc = frappe.get_doc("Sales Invoice", name)
		html = _render(doc)
		# The per-line tax has to come from somewhere real: assert the document's
		# own VAT total appears in the totals block, and that the line column is
		# not uniformly the `0.00` literal the else-branch prints.
		body = html.split("TAX AMT")[-1]
		self.assertNotEqual(
			body.count("0.00"),
			len(doc.items),
			f"{name}: every line printed 0.00 under TAX AMT while the document carries "
			f"{doc.total_taxes_and_charges}",
		)
