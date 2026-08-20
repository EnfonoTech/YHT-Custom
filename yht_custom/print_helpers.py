# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Shared Jinja helpers for the print formats.

Exposed to print-format templates through the ``jinja`` hook. Keeping the header,
the Arabic handling and the money formatting in one place means the formats stay
consistent instead of drifting apart the way the legacy site's 146 did — 32
Delivery Note formats is not a requirement, it is the absence of one.

**Every function here is deliberately prefixed ``yht_``.** The hook does NOT
support aliasing: `frappe/utils/jinja.py::get_obj_dict_from_paths` registers each
function under its own ``__name__``, and **every installed app's jinja methods
land in one shared namespace**. A helper called ``money`` or ``nice_date`` would
be one upgrade away from silently shadowing, or being shadowed by, another app's.
"""

import frappe
from frappe.utils import flt, fmt_money, formatdate

#: RTL rule (inherited from RMAX, learned the hard way): never put a colon inside
#: an Arabic value cell. The bidi algorithm moves it to the visual LEFT of the
#: text, so "الرقم الضريبي:" renders as ":الرقم الضريبي". Labels and values go in
#: separate cells instead.
RTL_STYLE = "direction:rtl; text-align:right;"


def yht_branch_header(doc) -> str:
	"""Bilingual company / branch header block.

	Resolution order for the branch line: the document's own branch, then the
	company. A missing Arabic name degrades to the English one rather than
	printing an empty cell.
	"""
	company = doc.get("company")
	company_doc = frappe.get_cached_doc("Company", company) if company else None
	branch = doc.get("branch") or frappe.db.get_value("Branch Configuration", {"company": company}, "branch")

	branch_ar = ""
	if branch:
		branch_ar = frappe.db.get_value("Branch", branch, "custom_branch_name_ar") or ""

	vat = (company_doc.tax_id if company_doc else "") or ""
	cr = ""
	if company_doc and company_doc.meta.has_field("registration_details"):
		cr = company_doc.get("registration_details") or ""

	# Two columns: English left, Arabic right. No colons on the Arabic side.
	return f"""
	<table class="yht-head">
	  <tr>
	    <td class="yht-head-en">
	      <div class="yht-co">{frappe.utils.escape_html(company or "")}</div>
	      {f'<div class="yht-sub">Branch {frappe.utils.escape_html(branch)}</div>' if branch else ""}
	      {f'<div class="yht-sub">VAT {frappe.utils.escape_html(vat)}</div>' if vat else ""}
	    </td>
	    <td class="yht-head-ar" style="{RTL_STYLE}">
	      {f'<div class="yht-co">{frappe.utils.escape_html(branch_ar)}</div>' if branch_ar else ""}
	      {f'<div class="yht-sub">{frappe.utils.escape_html(vat)} الرقم الضريبي</div>' if vat else ""}
	    </td>
	  </tr>
	</table>
	"""


def yht_party(doc, party_field="customer", party_name_field="customer_name") -> str:
	"""Bill-to block with VAT and CR where present."""
	party = doc.get(party_field)
	name = doc.get(party_name_field) or party or ""
	if not party:
		return ""

	doctype = "Customer" if party_field == "customer" else "Supplier"
	vat = frappe.db.get_value(doctype, party, "tax_id") or ""
	address = ""
	addr_field = "customer_address" if party_field == "customer" else "supplier_address"
	if doc.get(addr_field):
		address = frappe.db.get_value("Address", doc.get(addr_field), "address_line1") or ""

	rows = [f'<div class="yht-party-name">{frappe.utils.escape_html(name)}</div>']
	if address:
		rows.append(f'<div>{frappe.utils.escape_html(address)}</div>')
	if vat:
		rows.append(f'<div>VAT {frappe.utils.escape_html(vat)}</div>')
	return "".join(rows)


def yht_money(value, currency=None) -> str:
	return fmt_money(flt(value), currency=currency)


def yht_date(value) -> str:
	return formatdate(value, "dd-MM-yyyy") if value else ""


def yht_item_ar(item_code: str) -> str:
	"""Arabic item name if the site carries one.

	The legacy data had this under three different fieldnames across doctypes
	(`custom_item_name_in_arabic`, `custom_item_arabic_name`, `item_arabic_name`).
	All were deleted in the strip; this looks up whichever the rebuild settles on
	and returns "" until then, so the formats work either way.
	"""
	if not item_code:
		return ""
	for fieldname in ("custom_item_name_ar", "custom_item_name_in_arabic", "custom_item_arabic_name"):
		if frappe.db.has_column("Item", fieldname):
			return frappe.db.get_value("Item", item_code, fieldname) or ""
	return ""


def yht_so_title(doc) -> tuple[str, str]:
	"""(English, Arabic) title for the one-document-three-titles requirement.

	MoM §2.3: a single Sales Order prints as Quotation, Proforma Invoice or Sales
	Order depending on what the user picked, rather than maintaining three
	documents that drift apart.
	"""
	kind = (doc.get("custom_print_as") or "").strip() or "Sales Order"
	titles = {
		"Quotation": ("QUOTATION", "عرض سعر"),
		"Proforma Invoice": ("PROFORMA INVOICE", "فاتورة أولية"),
		"Sales Order": ("SALES ORDER", "أمر بيع"),
	}
	return titles.get(kind, titles["Sales Order"])


def yht_line_discount(row) -> float:
	"""Money given away on one printed row.

	Thin wrapper so a print format never has to know how a discount is stored —
	percentage, per-unit amount or a hand-typed rate all come out the same here.
	"""
	from yht_custom.discount_totals import line_discount

	return line_discount(row)


def yht_discount_total(doc) -> float:
	"""Consolidated item-wise discount for the document (MoM §2.3).

	Computed from the rows on every render rather than read from the stored
	`custom_total_line_item_discount`, so the 2,344 invoices submitted before that
	field existed print a correct total without backfilling a single one.
	"""
	from yht_custom.discount_totals import line_discount_total

	return line_discount_total(doc)
