# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""The KATC PDF download break (2026-10-13): Print Designer's request hook puts the format's own
`pdf_generator` (`wkhtmltopdf-shrink`) into the request and frappe's `download_pdf` refused it.

Runs on `yht-test` only:

    bench --site yht-test run-tests --app yht_custom --skip-before-tests \
        --module yht_custom.tests.test_print_download

The in-process tests exercise the type check the way a request does (`flags.in_test` turns
`validate_argument_types` on). The REAL HTTP path — which is what actually failed — is checked
by `scripts/check_pdf_download.py`, because a script call has no `before_request`.
"""

import inspect

import frappe
from frappe.exceptions import FrappeTypeError
from frappe.tests.utils import FrappeTestCase
from frappe.utils.print_format import download_pdf as upstream

from yht_custom import print_download
from yht_custom.pdf_shrink import PDF_GENERATOR


def _a_katc_doc():
	"""(doctype, name, format) of an enabled KATC format that routes through pdf_shrink."""
	for fmt in frappe.get_all(
		"Print Format",
		filters={"disabled": 0, "name": ["like", "KATC%"], "pdf_generator": PDF_GENERATOR},
		fields=["name", "doc_type"],
		order_by="name",
	):
		name = frappe.db.get_value(fmt.doc_type, {"docstatus": 1}, "name", order_by="modified desc")
		if name:
			return fmt.doc_type, name, fmt.name
	return None


class TestDownloadPdfOverride(FrappeTestCase):
	def setUp(self):
		self._form_dict = frappe.local.form_dict
		frappe.local.form_dict = frappe._dict(self._form_dict)

	def tearDown(self):
		frappe.local.form_dict = self._form_dict
		frappe.local.response.pop("filecontent", None)

	def test_the_override_is_registered_and_resolves(self):
		overrides = frappe.get_hooks("override_whitelisted_methods", app_name="yht_custom") or {}
		path = "frappe.utils.print_format.download_pdf"
		self.assertIn(path, overrides)
		target = overrides[path][-1] if isinstance(overrides[path], list) else overrides[path]
		self.assertIs(frappe.get_attr(target), print_download.download_pdf)

	def test_the_wrapper_is_whitelisted_and_guest_reachable_like_upstream(self):
		fn = frappe.get_attr("yht_custom.print_download.download_pdf")
		self.assertIn(fn, frappe.whitelisted)
		self.assertEqual(fn in frappe.guest_methods, upstream in frappe.guest_methods)

	def test_the_wrapper_has_the_upstream_signature(self):
		"""Same parameter names, same order, same defaults; only `pdf_generator`'s type differs."""
		ours = inspect.signature(inspect.unwrap(print_download.download_pdf)).parameters
		theirs = inspect.signature(inspect.unwrap(upstream)).parameters
		self.assertEqual(list(ours), list(theirs))
		for name in theirs:
			self.assertEqual(ours[name].default, theirs[name].default, name)

	def test_upstream_really_refuses_our_generator_name(self):
		"""Characterisation: this is the failure. If it stops raising, the wrapper is not needed."""
		found = _a_katc_doc()
		if not found:
			self.skipTest("no KATC format on this site routes through pdf_shrink")
		doctype, name, fmt = found
		with self.assertRaises(FrappeTypeError):
			upstream(doctype, name, fmt, pdf_generator=PDF_GENERATOR)

	def test_the_wrapper_renders_a_katc_format_with_the_request_hook_value(self):
		found = _a_katc_doc()
		if not found:
			self.skipTest("no KATC format on this site routes through pdf_shrink")
		doctype, name, fmt = found
		# What before_request leaves behind on /api/method/...download_pdf
		frappe.local.form_dict.pdf_generator = PDF_GENERATOR
		print_download.download_pdf(doctype, name, fmt, pdf_generator=PDF_GENERATOR)
		self.assertTrue(frappe.local.response.filecontent.startswith(b"%PDF"))
		self.assertEqual(frappe.local.response.type, "pdf")

	def test_the_wrapper_renders_without_a_request_hook_too(self):
		found = _a_katc_doc()
		if not found:
			self.skipTest("no KATC format on this site routes through pdf_shrink")
		doctype, name, fmt = found
		frappe.local.form_dict.pop("pdf_generator", None)
		print_download.download_pdf(doctype, name, fmt, pdf_generator=PDF_GENERATOR)
		self.assertTrue(frappe.local.response.filecontent.startswith(b"%PDF"))

	def test_a_literal_generator_is_passed_straight_through(self):
		seen = {}

		def fake(doctype, name, format=None, doc=None, no_letterhead=0, language=None, letterhead=None, pdf_generator=None):
			seen["pdf_generator"] = pdf_generator

		from unittest import mock

		with mock.patch.object(print_download, "_frappe_download_pdf", fake):
			print_download.download_pdf("Quotation", "X", pdf_generator="chrome")
			self.assertEqual(seen["pdf_generator"], "chrome")
			print_download.download_pdf("Quotation", "X", pdf_generator=PDF_GENERATOR)
			self.assertIsNone(seen["pdf_generator"])
			self.assertEqual(frappe.local.form_dict.get("pdf_generator"), PDF_GENERATOR)
