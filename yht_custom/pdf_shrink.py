# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Render a print format with wkhtmltopdf's smart shrinking LEFT ON.

🔴 WHY THIS EXISTS. `--disable-smart-shrinking` is itself a wkhtmltopdf PATCH-only
feature, and `frappe/utils/pdf.py::get_pdf` sets it unconditionally for any version
`> 0.12.3`. The unpatched Ubuntu build this bench used until 2026-09-12 simply
IGNORED it and always scaled the layout to fit the page, which is why the KATC
formats looked correct for weeks. The static patched build obeys it, renders 1:1,
and anything wider than A4 runs off the right-hand edge with no error at all.

Measured A/B on `KSIN-25-0432`, same document and same format: unpatched → 2 pages
carrying all seven columns; patched → 3 pages with **`Total Inc.Vat` missing
entirely** from a Saudi tax invoice. The widest format overflows by ~216 pt, about
a third of the page, so trimming margins cannot reach it — 5 mm margins bring the
last column back and still leave the document cramped across three pages.

The patched build is wanted for everything else it brought (page numbers, a
letterhead that repeats correctly through `#header-html`), so the fix is to keep
the engine and put the shrinking back for the formats that were designed against
it. `Print Format.pdf_generator` selects this renderer per format, so nothing else
on the bench changes behaviour.

⚠️ This deliberately duplicates `frappe.utils.pdf.get_pdf` minus one line. Every
piece of work is still done by frappe's own helpers — `scrub_urls`,
`prepare_options`, `cleanup` — so the only thing that can drift on an upgrade is
the surrounding shape. **If a frappe upgrade changes `get_pdf`, re-read it against
this.** Editing `apps/frappe` instead is not an option; it does not survive.
"""

import io

import frappe
import pdfkit
from frappe import _
from frappe.utils.pdf import (
	PDF_CONTENT_ERRORS,
	cleanup,
	get_file_data_from_writer,
	prepare_options,
	scrub_urls,
)
from pypdf import PdfReader, PdfWriter

#: Put this in `Print Format.pdf_generator` to route a format through here.
PDF_GENERATOR = "wkhtmltopdf-shrink"


def render(print_format=None, html=None, options=None, output=None, pdf_generator=None, **kwargs):
	"""`pdf_generator` hook. Returns bytes for our formats, None for everyone else.

	`frappe.utils.print_utils.get_print` calls every registered hook in turn and
	takes the first one that returns a value, so returning None for a generator we
	do not own leaves the stock wkhtmltopdf path untouched.
	"""
	if pdf_generator != PDF_GENERATOR:
		return None

	html = scrub_urls(html)
	html, options = prepare_options(html, options)
	options.update({"disable-javascript": "", "disable-local-file-access": ""})
	# 🔴 THE WHOLE POINT: `get_pdf` would add `disable-smart-shrinking` here.
	# We do not, so wkhtmltopdf scales the layout to the page as it used to.

	filedata = ""
	reader = None
	try:
		filedata = pdfkit.from_string(html, options=options or {}, verbose=True)
		reader = PdfReader(io.BytesIO(filedata))
	except OSError as e:
		if any(error in str(e) for error in PDF_CONTENT_ERRORS):
			if not filedata:
				frappe.throw(_("PDF generation failed because of broken image links"))
			# A PDF was produced despite a missing image — keep it, as frappe does.
			if output and reader:
				output.append_pages_from_reader(reader)
		else:
			raise
	finally:
		cleanup(options)

	if reader is None:
		return None

	if output:
		output.append_pages_from_reader(reader)
		return output

	writer = PdfWriter()
	writer.append_pages_from_reader(reader)
	if "password" in options:
		writer.encrypt(options["password"])
	return get_file_data_from_writer(writer)
