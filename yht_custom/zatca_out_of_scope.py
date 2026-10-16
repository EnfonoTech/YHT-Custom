# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""An invoice that only covers supplies "Not subject to VAT" is not sent to ZATCA (client, 2026-10-16).

The client quoted ZATCA's own E-Invoicing Detailed Guideline (FAQ, page 62):

	"Do we need to send to ZATCA the invoices where all sold items and services are 'Services outside
	scope of tax / Not subject to VAT'? ... The Tax Category Code O is for those transactions where an
	invoice may contain a line item with Standard Rate supply and other with 'Not Subject to VAT'.
	There is no need to issue a Tax Invoice (or E-Invoice) where the transaction solely covers supplies
	which are 'Not Subject to VAT'. Note: if the 'Not Subject to VAT' supply invoices are generated using
	the same billing solution that generates invoices for Standard Rate, there should not be gaps in
	Counter Value and the sequence of Previous Invoice Hash."

The case that raised it: a branch billing another branch of the same VAT registration. ZATCA rejects a
standard invoice whose seller and buyer share a VAT number (BR-CUSTOM-VALIDATION-01); those transactions are
entered with the "Zero Rated" tax (Tax Category 'Zero Rated', ZATCA category O, reason VATEX-SA-OOS).

## What this does

`ksa_compliance` creates the Sales Invoice Additional Fields record, which is what builds, signs and reports the
e-invoice, in its own `on_submit` handler. That handler first checks an in-process ignore list
(`sales_invoice.ignore_additional_fields_for_invoice`). We add the invoice to that list in `before_submit`, which
always runs before any `on_submit`, when EVERY line is category O. Result: no Sales Invoice Additional Fields,
no signing, no report. The ZATCA invoice counter and hash chain are only advanced by a generated e-invoice,
so a skipped invoice cannot leave a gap in them.

## When an invoice qualifies

Either of two things, and never anything else:

1. every line is category O, decided exactly as `ksa_compliance` does it (below); or
2. the invoice HEADER's Sales Taxes template is category O (Tax Category 'Zero Rated') AND no tax is charged
   (`total_taxes_and_charges` is 0). This is how the client enters these invoices: they pick the 'Zero Rated'
   header, but ERPNext still fills each line's item tax template from the Item master (typically 'SALES VAT 15%'),
   so the app classes the line S although nothing is charged — KSIN-26-0747 — and would report an invoice
   that contradicts itself (BR-CO-17 / BR-S-09 warnings). What is charged decides, as the client put it:
   "if tax is not calculated it is not kept in ZATCA".

## How a line's category is decided

Exactly as `ksa_compliance.output_models.tax.create_tax_categories` does it, by calling the same
`map_tax_category`: with a Sales Taxes template and NO item tax template on any line, the template's Tax Category
decides for all lines; otherwise each line uses its own item tax template (or the template's Tax Category when it
has none). An invoice with one line that is not O, a line with no category, or anything we cannot read is sent
as before — the default is always "report it".

An invoice with real tax charged, a header that is not O and a mix of categories is reported as before.

Behind `oct16_zatca_skip_out_of_scope`: off, nothing here runs.
"""

import frappe
from frappe.utils import cstr, flt

from yht_custom import features

FEATURE = "oct16_zatca_skip_out_of_scope"
OUT_OF_SCOPE = "O"


def line_categories(doc):
	"""The ZATCA category code of every item line, as ksa_compliance decides it; `None` if it cannot be read."""
	from ksa_compliance.standard_doctypes.tax_category import map_tax_category

	rows = list(doc.get("items") or [])
	if not rows:
		return None
	template = doc.get("taxes_and_charges")

	def template_category():
		tax_category = frappe.db.get_value("Sales Taxes and Charges Template", template, "tax_category") if template else None
		return map_tax_category(tax_category_id=tax_category).tax_category_code if tax_category else None

	if template and not any(row.get("item_tax_template") for row in rows):
		code = template_category()
		return [code] * len(rows) if code else None

	codes = []
	for row in rows:
		item_template = row.get("item_tax_template")
		if item_template:
			codes.append(map_tax_category(item_tax_template_id=item_template).tax_category_code)
		elif template:
			codes.append(template_category())
		else:
			return None
	return codes


def header_is_out_of_scope_without_tax(doc) -> bool:
	"""The header Sales Taxes template is category O and no tax is charged."""
	from ksa_compliance.standard_doctypes.tax_category import map_tax_category

	template = doc.get("taxes_and_charges")
	if not template or flt(doc.get("total_taxes_and_charges")) != 0:
		return False
	tax_category = frappe.db.get_value("Sales Taxes and Charges Template", template, "tax_category")
	return bool(tax_category) and map_tax_category(tax_category_id=tax_category).tax_category_code == OUT_OF_SCOPE


def is_out_of_scope_only(doc) -> bool:
	"""True when the invoice qualifies (see the module docstring)."""
	if not doc.get("items"):
		return False
	if header_is_out_of_scope_without_tax(doc):
		return True
	codes = line_categories(doc)
	return bool(codes) and all(code == OUT_OF_SCOPE for code in codes)


def skip_zatca_for_out_of_scope(doc, method=None):
	"""`Sales Invoice.before_submit` — keep an out-of-scope-only invoice out of ZATCA. Never raises."""
	if not features.enabled(FEATURE) or doc.doctype != "Sales Invoice":
		return
	try:
		if not is_out_of_scope_only(doc):
			return
		from ksa_compliance.standard_doctypes.sales_invoice import ignore_additional_fields_for_invoice

		ignore_additional_fields_for_invoice(doc.name)
		frappe.msgprint(
			"This invoice is not reported to ZATCA: it is 'Services outside scope of tax / Not subject to VAT' with no tax charged.",
			alert=True,
			indicator="orange",
		)
		doc.add_comment(
			"Info",
			"Not reported to ZATCA: the supply is 'Services outside scope of tax / Not subject to VAT' and no tax is charged "
			"(ZATCA E-Invoicing Detailed Guideline, FAQ: no tax invoice is needed for such supplies).",
		)
	except Exception:
		# The safe default is the old behaviour: the invoice is reported.
		frappe.log_error(title="yht_custom: ZATCA out-of-scope skip", message=f"{cstr(doc.name)}\n{frappe.get_traceback()}")
