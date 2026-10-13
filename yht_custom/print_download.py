# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""`frappe.utils.print_format.download_pdf`, taught to accept our own PDF generator name.

🔴 WHAT BROKE (found 2026-10-13, UAT and, by the same code, live). Print Designer's
`before_request` hook (`print_designer.pdf_generator.pdf.before_request`) copies the print
format's own `pdf_generator` column into `frappe.form_dict` for every
`/api/method/frappe.utils.print_format.download_pdf` request. Every `KATC *` format stores
`wkhtmltopdf-shrink` there — that is how `pdf_shrink.render` is routed to (gotcha 104). Frappe's
`download_pdf` declares `pdf_generator: Literal["wkhtmltopdf", "chrome"] | None`, and
`@frappe.whitelist()` wraps the function in `validate_argument_types`, so the request died with
HTTP 417 `FrappeTypeError` before a single line of the print ran. Before Print Designer was
installed nothing injected the value, so the same call worked. A PDF made in a script (no request,
so no hook) never showed it, which is why the install check missed it.

THE FIX. Override the endpoint (`override_whitelisted_methods` IS honoured by `handler.execute_cmd`,
gotcha 118) with a wrapper whose `pdf_generator` is a plain string. It hands frappe's own function
`None` where the value is not one frappe accepts, and leaves the value in `frappe.form_dict`, which is
where `print_utils.get_print` reads it before choosing a generator hook:

    if "pdf_generator" not in local.form_dict:      # already set by before_request
        ...
    if local.form_dict.pdf_generator != "wkhtmltopdf":
        for hook in frappe.get_hooks("pdf_generator"): ...   # -> pdf_shrink.render

so routing is unchanged and `wkhtmltopdf` / `chrome` values pass straight through as before.

⚠️ This calls the upstream function rather than copying it, so permission checks, the language
context, the response headers and the filename stay frappe's. The upstream function is ALSO wrapped
in `validate_argument_types`, which is why `None` and not the raw string is what it is given.
If a frappe upgrade changes `download_pdf`'s signature, `test_the_wrapper_has_the_upstream_signature`
fails — re-read it against this file.
"""

import frappe
from frappe.utils.print_format import download_pdf as _frappe_download_pdf

#: The only values frappe's own type check accepts.
FRAPPE_GENERATORS = ("wkhtmltopdf", "chrome")


@frappe.whitelist(allow_guest=True)
def download_pdf(
	doctype: str,
	name: str,
	format: str | None = None,
	doc=None,
	no_letterhead: bool | int = 0,
	language: str | None = None,
	letterhead: str | None = None,
	pdf_generator: str | None = None,
):
	passed = pdf_generator if pdf_generator in FRAPPE_GENERATORS else None
	if pdf_generator and passed is None and "pdf_generator" not in frappe.local.form_dict:
		# Called with one of our generator names and no request hook to have set it: put it where
		# `get_print` looks, exactly as the hook would have.
		frappe.local.form_dict.pdf_generator = pdf_generator

	return _frappe_download_pdf(
		doctype,
		name,
		format,
		doc,
		no_letterhead,
		language,
		letterhead,
		passed,
	)
