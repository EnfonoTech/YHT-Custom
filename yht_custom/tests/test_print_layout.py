# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Layout invariants for the print formats, both learned from production faults.

Neither of these is a style preference. Each one shipped, reached the client, and
was reported by them:

* **A blank first page.** The letterhead used to be a row of the outer table, so
  the table broke BETWEEN it and the body whenever the body's first chunk did not
  fit underneath — page 1 carried the letterhead and nothing else. It is
  content-dependent, which is exactly why a single sample proves nothing: across
  eight quotations, KSSQ-26-0767 (18 lines) blanked while KSSQ-26-0762 (19 lines)
  did not.
* **A clipped right edge.** `--disable-smart-shrinking` is a wkhtmltopdf
  patch-only feature that frappe sets unconditionally; the unpatched build ignored
  it. After the engine swap the Tax Invoice printed with no `Total Inc.Vat`
  column. `yht_custom.pdf_shrink` puts the shrinking back, per format.
"""

import io

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom.pdf_shrink import PDF_GENERATOR, render

#: Formats designed against the shrinking engine. The legacy reproduction is NOT
#: here on purpose — it is built at the incumbent's own widths and fits at 1:1.
LEGACY_REPRODUCTIONS = {"KATHOOM KHOBAR INV FORMAT NEW"}


def _katc_formats():
	return frappe.db.sql(
		"""select name, doc_type, ifnull(pdf_generator, '') as pdf_generator
		   from `tabPrint Format`
		   where ifnull(module, '') = 'Yht Custom' and ifnull(disabled, 0) = 0
		     and name like 'KATC%'""",
		as_dict=True,
	)


class TestTheShrinkGeneratorIsWired(FrappeTestCase):
	def test_the_hook_is_registered(self):
		hooks = frappe.get_hooks("pdf_generator") or []
		self.assertIn("yht_custom.pdf_shrink.render", hooks)

	def test_it_declines_anything_that_is_not_ours(self):
		"""Returning None is what lets frappe fall through to stock wkhtmltopdf.

		Returning a value here would hijack every other format on the bench.
		"""
		self.assertIsNone(render(print_format="X", html="<p>x</p>", pdf_generator="wkhtmltopdf"))
		self.assertIsNone(render(print_format="X", html="<p>x</p>", pdf_generator=None))

	def test_every_katc_format_asks_for_the_shrinking_renderer(self):
		formats = _katc_formats()
		self.assertTrue(formats, "no KATC formats installed — the check would pass vacuously")
		missing = [f.name for f in formats if f.pdf_generator != PDF_GENERATOR]
		self.assertFalse(missing, f"these would clip at the right edge again: {missing}")

	def test_the_legacy_reproduction_stays_on_the_stock_renderer(self):
		for name in LEGACY_REPRODUCTIONS:
			if not frappe.db.exists("Print Format", name):
				continue
			self.assertFalse(
				frappe.db.get_value("Print Format", name, "pdf_generator"),
				f"{name} reproduces the incumbent at 1:1 and must not be shrunk",
			)


class TestTheLetterheadCannotForceAPageBreak(FrappeTestCase):
	def test_no_format_puts_the_letterhead_inside_the_document_table(self):
		"""The structural cause, asserted on the source rather than on a render.

		`id="header-html"` is extracted by `prepare_header_footer` and drawn in the
		page margin, so it can neither consume body space nor force a break.
		"""
		for f in _katc_formats():
			html = frappe.db.get_value("Print Format", f.name, "html") or ""
			if "katc-doc" not in html and "{% include" in html:
				path = html.split('"')[1].replace("yht_custom/", "", 1)
				html = open(f"{frappe.get_app_path('yht_custom')}/{path}", encoding="utf-8").read()
			if "letter_head" not in html:
				continue
			with self.subTest(print_format=f.name):
				head = html.find("letter_head and")
				self.assertGreater(head, -1)
				window = html[max(0, head - 400) : head]
				self.assertIn(
					'id="header-html"',
					window,
					f"{f.name}: the letterhead is not in a #header-html block, so it can "
					f"break the page between itself and the body",
				)

	def test_a_document_that_used_to_blank_its_first_page_now_prints_on_it(self):
		"""The end-to-end check, on the exact document that failed in production."""
		name = frappe.db.get_value("Quotation", {"name": "KSSQ-26-0767"}, "name")
		if not name:
			rows = frappe.db.sql(
				"""select q.name from `tabQuotation` q join `tabQuotation Item` it on it.parent = q.name
				   group by q.name having count(*) = 18 limit 1"""
			)
			if not rows:
				self.skipTest("no comparable quotation on this site")
			name = rows[0][0]

		from pypdf import PdfReader

		from frappe.utils.print_format import download_pdf

		frappe.local.response = frappe._dict()
		download_pdf("Quotation", name, format="KATC Quotation", no_letterhead=0, letterhead="KATC Letterhead")
		page1 = PdfReader(io.BytesIO(frappe.local.response.filecontent)).pages[0].extract_text() or ""
		self.assertIn(name, page1, f"{name}: page 1 carries the letterhead and nothing else")
