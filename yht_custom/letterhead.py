# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Bilingual per-branch letterhead (plan 6.5).

WHAT WAS THERE. One Letter Head, `KATHOOM ALKHOBAR`, `source = Image`, pointing at
`/files/KhobarHeading1.jpg`. An image letterhead cannot be bilingual in any useful
sense — it cannot carry the branch's Arabic name, it cannot pick up a VAT number
change, and it cannot be read by anything. 1,515 Sales Invoices reference it.

WHAT THIS BUILDS. One HTML Letter Head per Branch, generated from live data:
company name, the branch's Arabic name, VAT, CR, the company address and its
contact details. English left, Arabic right.

WHAT THIS DELIBERATELY DOES NOT DO. It does not touch
`Company.default_letter_head`. That still points at the image, and switching it
would silently change how 1,515 historical invoices print — the client's existing
branding, and their decision to retire, not ours. The new letterhead is created,
linked to the Branch, and available in the print dialog.

It also does not replace `print_helpers.yht_branch_header`. Our four formats draw
their own header, tuned per document, and empirically frappe does NOT inject a
letterhead into them — verified by rendering `KSDN-26-0526`, whose `letter_head`
is `KATHOOM ALKHOBAR`: the output contains no image and exactly the two headers
the two copies each draw. Wiring the letterhead into those formats as well would
produce two headers where there is currently one.

ONE ODDITY WORTH KNOWING: 1,266 documents (832 Sales Invoices, 212 Delivery
Notes, 176 Quotations, 46 Sales Orders) point at a Letter Head named
`Kathoom without letterhead` that does not exist. Printing them does NOT fail —
frappe degrades to no letterhead, which is what the name asks for. Left alone.
"""

import frappe
from frappe.utils import cstr

#: Prefixed so a generated letterhead can never be confused with the client's own.
PREFIX = "YHT "

#: No colons inside an Arabic value cell. The bidi algorithm moves a trailing
#: colon to the visual LEFT of the text, so "الرقم الضريبي:" renders as
#: ":الرقم الضريبي". Label and value go in separate cells instead.
RTL = "direction:rtl; text-align:right;"


def letter_head_name(branch: str) -> str:
	return f"{PREFIX}{branch}"


def setup_branch_letterheads() -> dict:
	"""Create or refresh one HTML Letter Head per Branch. Idempotent.

	Rewrites content only when it actually differs, so a migrate on an unchanged
	site touches nothing.
	"""
	created, updated, unchanged = 0, 0, 0

	for branch in frappe.get_all("Branch", pluck="name"):
		content = build_content(branch)
		footer = build_footer(branch)
		name = letter_head_name(branch)

		if frappe.db.exists("Letter Head", name):
			doc = frappe.get_doc("Letter Head", name)
			if doc.content == content and doc.footer == footer:
				unchanged += 1
			else:
				doc.source = "HTML"
				doc.content = content
				doc.footer = footer
				doc.flags.ignore_permissions = True
				doc.save()
				updated += 1
		else:
			frappe.get_doc(
				{
					"doctype": "Letter Head",
					"letter_head_name": name,
					"source": "HTML",
					"content": content,
					"footer": footer,
					# Never default. Company.default_letter_head is the client's image
					# letterhead and 1,515 invoices print with it.
					"is_default": 0,
					"disabled": 0,
				}
			).insert(ignore_permissions=True)
			created += 1

		if frappe.db.has_column("Branch", "custom_letter_head"):
			frappe.db.set_value("Branch", branch, "custom_letter_head", name, update_modified=False)

	return {"created": created, "updated": updated, "unchanged": unchanged}


# ------------------------------------------------------------------- rendering


def _company():
	name = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	if not name:
		return None
	return frappe.get_cached_doc("Company", name)


def _company_address(company: str) -> dict:
	rows = frappe.db.get_all(
		"Address",
		filters=[
			["Dynamic Link", "link_doctype", "=", "Company"],
			["Dynamic Link", "link_name", "=", company],
		],
		fields=[
			"address_line1",
			"address_line2",
			"city",
			"pincode",
			"phone",
			"email_id",
			"custom_building_number",
			"custom_area",
		],
		limit=1,
	)
	return rows[0] if rows else {}


def _english_address(address: dict) -> str:
	"""National-address order: building, street, district, city, postal code."""
	parts = [
		address.get("custom_building_number") or address.get("address_line1"),
		address.get("address_line2"),
		address.get("custom_area"),
		address.get("city"),
		address.get("pincode"),
	]
	return ", ".join(cstr(part).strip() for part in parts if cstr(part).strip())


def build_content(branch: str) -> str:
	"""Bilingual header markup.

	The `<tbody>` is written out by hand. Frappe normalises HTML on save and adds
	one itself, so markup without it never round-trips: the stored content came
	back 15 bytes longer than what was generated (`<tbody>` + `</tbody>`), the
	idempotency check compared unequal, and every single migrate rewrote every
	letterhead.
	"""
	company = _company()
	if not company:
		return ""

	address = _company_address(company.name)
	branch_ar = cstr(frappe.db.get_value("Branch", branch, "custom_branch_name_ar"))
	vat = cstr(company.tax_id)
	cr = cstr(company.get("registration_details"))
	escape = frappe.utils.escape_html

	english = [f'<div class="yht-lh-co">{escape(company.name)}</div>']
	if branch := cstr(branch):
		english.append(f'<div class="yht-lh-sub">Branch {escape(branch)}</div>')
	if line := _english_address(address):
		english.append(f'<div class="yht-lh-sub">{escape(line)}</div>')
	if vat:
		english.append(f'<div class="yht-lh-sub">VAT {escape(vat)}</div>')
	if cr:
		english.append(f'<div class="yht-lh-sub">CR {escape(cr)}</div>')

	arabic = []
	if branch_ar:
		arabic.append(f'<div class="yht-lh-co">{escape(branch_ar)}</div>')
	if vat:
		arabic.append(f'<div class="yht-lh-sub">{escape(vat)} الرقم الضريبي</div>')
	if cr:
		arabic.append(f'<div class="yht-lh-sub">{escape(cr)} السجل التجاري</div>')

	return f"""<div class="yht-letterhead">
<style>
.yht-letterhead {{ font-family: "Helvetica Neue", Arial, sans-serif; }}
.yht-letterhead table {{ width: 100%; border-bottom: 2px solid #000; }}
.yht-letterhead td {{ vertical-align: top; padding: 2px 0 6px; width: 50%; }}
.yht-lh-co {{ font-size: 13pt; font-weight: bold; }}
.yht-lh-sub {{ font-size: 8.5pt; }}
</style>
<table>
  <tbody><tr>
    <td>{''.join(english)}</td>
    <td style="{RTL}">{''.join(arabic)}</td>
  </tr></tbody>
</table>
</div>"""


def build_footer(branch: str) -> str:
	company = _company()
	if not company:
		return ""

	address = _company_address(company.name)
	escape = frappe.utils.escape_html
	bits = [
		cstr(address.get("phone")) or cstr(company.phone_no),
		cstr(address.get("email_id")) or cstr(company.email),
		cstr(company.website),
	]
	line = "  ·  ".join(escape(bit.strip()) for bit in bits if bit and bit.strip())
	if not line:
		return ""

	return (
		'<div style="border-top:1px solid #999; padding-top:3px; text-align:center;'
		f' font-size:8pt; color:#444;">{line}</div>'
	)
