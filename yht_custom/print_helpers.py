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

import json

import frappe
from frappe.utils import cint, cstr, flt, fmt_money, formatdate

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


#: Step 4, MEASURED on `yht-test` (a copy of client data), not guessed. The Arabic
#: item name lives on the CHILD ROW, in bulk, under a different fieldname per
#: parent doctype:
#:
#:     Sales Invoice Item  custom_item_arabic_name      11,507 rows
#:     Sales Invoice Item  item_arabic_name (older)      8,055 rows
#:     Quotation Item      custom_item_name_in_arabic   20,850 rows
#:     Delivery Note Item  custom_item_name_in_arabic    7,356 rows
#:     Sales Order Item    custom_item_name_in_arabic    6,096 rows
CHILD_ARABIC_FIELDS = {
	"Sales Invoice Item": ("custom_item_arabic_name", "item_arabic_name"),
	"Quotation Item": ("custom_item_name_in_arabic",),
	"Delivery Note Item": ("custom_item_name_in_arabic",),
	"Sales Order Item": ("custom_item_name_in_arabic",),
}

#: Item-level fallback, in order. `custom_item_name_arabic` is the one field that
#: still EXISTS (0 populated rows); `custom_item_name_in_arabic` is orphaned data —
#: see `yht_item_ar`.
ITEM_ARABIC_FIELDS = ("custom_item_name_arabic", "custom_item_name_in_arabic")


def _item_ar_cache() -> dict:
	"""Per-request memo for the Item fallback.

	Lives on `frappe.local`, so it is discarded at the end of the request and can
	never serve a stale name into a later print.
	"""
	cache = getattr(frappe.local, "yht_item_ar_cache", None)
	if cache is None:
		cache = {}
		frappe.local.yht_item_ar_cache = cache
	return cache


def clear_item_ar_cache() -> None:
	"""Drop the memo. For tests, and for anything that edits an Item mid-request."""
	frappe.local.yht_item_ar_cache = {}


def _item_ar_from_item(item_code) -> str:
	"""Item-level fallback, memoised by item_code.

	One query per DISTINCT item_code per request, reading every candidate column in
	that single query. A query per ROW is an N+1 — on a 50-line document where no
	child row carries Arabic it is 50 reads — and this repo treats that as a
	blocker.
	"""
	item_code = cstr(item_code).strip()
	if not item_code:
		return ""

	cache = _item_ar_cache()
	if item_code in cache:
		return cache[item_code]

	fields = [f for f in ITEM_ARABIC_FIELDS if frappe.db.has_column("Item", f)]
	value = ""
	if fields:
		row = frappe.db.get_value("Item", item_code, fields, as_dict=True) or {}
		for fieldname in fields:
			value = cstr(row.get(fieldname)).strip()
			if value:
				break

	cache[item_code] = value
	return value


def yht_item_ar(row_or_item_code) -> str:
	"""Arabic item name — child row first, Item only as a fallback.

	Accepts EITHER a printed child row or a bare `item_code` string. Both callers
	are real: the six existing `YHT *` formats call `yht_item_ar(row.item_code)`
	and their behaviour must not change, while the KATC formats pass the row.

	Resolution order:

	1. **The child row**, under the fieldname that parent doctype actually uses
	   (`CHILD_ARABIC_FIELDS`). The row is already loaded, so this costs NO query —
	   which is the whole point, because this runs once per printed line.
	2. **The Item**, `custom_item_name_arabic` then `custom_item_name_in_arabic`,
	   memoised per request.
	3. `""`. Never `None` — a format renders this straight into a cell.

	ORPHANED DATA, STATED PLAINLY RATHER THAN HIDDEN IN A COMMENT:
	`Item.custom_item_name_in_arabic` has a **column and 3,857 populated rows but
	no DocField** — the field was purged in Step 1 and its data was left behind
	(gotcha 22: deleting a Custom Field drops neither the column nor the values).
	It is read here only as a last resort, and only because throwing away 3,857
	real Arabic names would be worse. It is NOT a supported field: it cannot be
	edited in the desk, it will not survive a table rebuild, and nothing keeps it
	in step with `custom_item_name_arabic`. Whether to restore the DocField or drop
	the column is an open decision for the client, not something to settle by
	quietly deleting this branch.
	"""
	if not row_or_item_code:
		return ""

	if isinstance(row_or_item_code, str):
		return _item_ar_from_item(row_or_item_code)

	row = row_or_item_code
	for fieldname in CHILD_ARABIC_FIELDS.get(cstr(row.get("doctype")), ()):
		value = cstr(row.get(fieldname)).strip()
		if value:
			return value

	return _item_ar_from_item(row.get("item_code"))


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


def yht_currency(doc) -> str:
	"""Currency for a printed document, resolved WITHOUT touching the sandbox.

	`frappe.defaults.get_global_default` is NOT reachable from a print format.
	Frappe hands the template a restricted `frappe` namespace in which `defaults`
	is a function, so the expression raises

	    'function object' has no attribute 'get_global_default'

	Every format here carried `doc.currency or frappe.defaults.get_global_default(
	"currency")` and got away with it only because `doc.currency` was always
	truthy — Python never evaluated the right-hand side. Journal Entry has no
	`currency` field at all, so it was the first document to reach it, and the
	whole format failed to render.

	This helper is ordinary server-side Python, so it can look anything up.
	"""
	currency = cstr(doc.get("currency")).strip()
	if currency:
		return currency

	company = doc.get("company")
	if company:
		company_currency = frappe.get_cached_value("Company", company, "default_currency")
		if company_currency:
			return company_currency

	return frappe.defaults.get_global_default("currency") or "SAR"


# ------------------------------------------------------ the KATC client prints
# Everything below serves the seven `KATC *` formats — the client's incumbent
# printing, recreated. Same yht_ prefix rule as above: ONE shared jinja namespace
# across every installed app, and the hook cannot alias.


def yht_katc_lh() -> str:
	"""The KATC HTML letterhead's record name.

	So that no print format and no test hard-codes the string. `katc_letterhead`
	is the single source of truth on the Python side; the button JS carries the
	one unavoidable duplicate, and a test asserts the two agree.
	"""
	from yht_custom.katc_letterhead import KATC_LETTER_HEAD

	return KATC_LETTER_HEAD


def yht_katc_email() -> str:
	"""The sales mailbox the client's artefacts print in their contact block.

	Same reason as `yht_katc_lh`: the address was a literal in two format bodies
	AND in `katc_letterhead.EMAIL`, which is three copies of one fact. The
	letterhead module owns the artefact's literals; the formats read them.
	"""
	from yht_custom.katc_letterhead import EMAIL

	return EMAIL


def yht_katc_spacer_pt() -> int:
	"""Height of the `Print Without LH` spacer, in points.

	Same reason as `yht_katc_lh`: seven formats and the test suite have to agree
	on this number, and seven literals plus a regex is seven places to get it
	wrong. `katc_letterhead.NO_LH_SPACER_PT` carries the measurement and the
	reason for it.
	"""
	from yht_custom.katc_letterhead import NO_LH_SPACER_PT

	return NO_LH_SPACER_PT


def yht_company_vat(doc) -> str:
	"""The SELLER's VAT registration number, from `Company.tax_id`.

	Spec Step 10's `VAT #` line. It is a helper and not
	`frappe.db.get_value("Company", …)` inside the template for the same reason
	`yht_bank_details` is: the print jinja environment binds `frappe.db` to
	`safe_exec`'s permission-checked namespace, so a template read is one
	permission edit away from a bare `PermissionError` on a customer-facing
	invoice. (`Company` read IS granted to `Branch User` today — `setup.py`
	line 53 — which is exactly why the dependency should not be invisible.)

	Empty string when the document carries no company or the company has no
	`tax_id`; the calling format then omits the line rather than printing
	`VAT # None`.
	"""
	company = doc.get("company") if hasattr(doc, "get") else None
	if not company:
		return ""

	return cstr(frappe.db.get_value("Company", company, "tax_id")).strip()


#: Fields the Saudi national address is assembled from. `address_line1` IS the
#: ZATCA street name and `custom_area` IS the district — see `saudi_address`.
#: `custom_building_number` / `custom_area` come from ksa_compliance;
#: `custom_additional_number` is ours.
_NATIONAL_ADDRESS_MAP = (
	("building", "custom_building_number"),
	("street", "address_line1"),
	("district", "custom_area"),
	("city", "city"),
	("pincode", "pincode"),
	("additional", "custom_additional_number"),
	("country", "country"),
)

#: Read alongside the map above so `_derive_building_and_street` can fall back to
#: the fields this client's data ACTUALLY uses.
_ADDRESS_EXTRA_FIELDS = ("address_line2",)


def _derive_building_and_street(result: dict, row: dict) -> None:
	"""Put the building number and the street in the right cells.

	🔴 THE STRAIGHT MAP PRINTS THE BUILDING NUMBER AS THE STREET NAME. Measured on
	this site's 577 Saudi addresses:

	  * `custom_building_number` — our own custom field — is set on **43**
	  * `address_line1` is set on **577**, and is PURELY NUMERIC on **362**
	  * `address_line2` is set on **397**

	So the client keeps the building number in `address_line1` and the street in
	`address_line2`. Reading `address_line1` as the street printed `6823` under
	"Street Name" on `VTSI-KT-6925` while the incumbent printed "Prince Sultan
	Road" for the same document.

	The rule, in order:
	  * building — our custom field if someone filled it, else `address_line1`
	    when it is nothing but digits
	  * street  — `address_line2` if present, else `address_line1` when it is NOT
	    purely numeric (an address written the ordinary way, all on one line)

	Anything unrecognised stays blank rather than guessing: a wrong street on a
	ZATCA invoice is worse than an empty one.
	"""
	line1 = cstr(row.get("address_line1")).strip()
	line2 = cstr(row.get("address_line2")).strip()
	line1_is_number = bool(line1) and line1.isdigit()

	if not result.get("building") and line1_is_number:
		result["building"] = line1

	if line2:
		result["street"] = line2
	elif line1_is_number:
		# line1 was the building number and there is no line2 — no street on file.
		result["street"] = ""
	else:
		result["street"] = line1


def yht_national_address(doc, address_field: str = "customer_address") -> dict:
	"""Saudi national address for the linked `Address`, as seven string keys.

	`{building, street, district, city, pincode, additional, country}`, every one
	defaulting to `""` — a print format renders these straight into cells, so
	`None` would print the word "None".

	ONE read per document, not one per field and certainly not one per row.

	⚠️ THE "578 OF 578 HAVE NO DISTRICT" FIGURE WAS MEASURED AGAINST THE WRONG
	FIELD. It counted `custom_area`, which our own provisioning created and which
	is populated on **0 of 577** addresses. The district this client actually
	types lives in `county`, populated on **320**. `county` is not clean — some
	rows carry a city there, some a region — so it is deliberately NOT mapped
	here yet; that needs the client to say which is authoritative. Recorded so
	the next person does not repeat the measurement.

	A missing or deleted Address returns all-empty rather than raising. Nothing
	about a print may depend on the buyer having a complete address — that is the
	ZATCA worklist's problem (`saudi_address.national_address_gaps`), not the
	invoice's.
	"""
	blank = {key: "" for key, _fieldname in _NATIONAL_ADDRESS_MAP}

	address = doc.get(address_field) if hasattr(doc, "get") else None
	if not address:
		return blank

	# Guarded: `custom_additional_number` is created by our own provisioning, so on
	# a site that has not migrated yet a bare read would raise instead of degrade.
	available = [
		(key, fieldname)
		for key, fieldname in _NATIONAL_ADDRESS_MAP
		if frappe.db.has_column("Address", fieldname)
	]
	if not available:
		return blank

	extra = [f for f in _ADDRESS_EXTRA_FIELDS if frappe.db.has_column("Address", f)]
	row = frappe.db.get_value(
		"Address", address, [f for _k, f in available] + extra, as_dict=True
	)
	if not row:
		return blank

	result = dict(blank)
	for key, fieldname in available:
		result[key] = cstr(row.get(fieldname)).strip()
	_derive_building_and_street(result, row)
	return result


def yht_party_vat(doc, party_field: str = "customer") -> str:
	"""The buyer's VAT registration number, for the tax-invoice buyer block.

	🔴 `doc.tax_id` IS OFTEN EMPTY ON HISTORICAL DOCUMENTS. It is copied from the
	Customer when the document is created, so anything imported — or created
	before the Customer's `tax_id` was filled in — carries NULL and printed a
	blank "VAT Number" cell while the incumbent printed the number. Measured on
	`VTSI-KT-6925`: `Sales Invoice.tax_id` is NULL, `Customer.tax_id` is
	311278176700003.

	So: the document's own value wins (it is what was true at invoice time and is
	what ZATCA reported), and the Customer is the fallback for the rows that never
	got one. `frappe.db.get_value`, not `get_doc` — it runs no permission check,
	so a branch user still gets a complete invoice.
	"""
	stored = cstr(doc.get("tax_id") if hasattr(doc, "get") else "").strip()
	if stored:
		return stored

	party = doc.get(party_field) if hasattr(doc, "get") else None
	if not party:
		return ""
	doctype = "Customer" if party_field == "customer" else "Supplier"
	return cstr(frappe.db.get_value(doctype, party, "tax_id") or "").strip()


def yht_sales_person(doc) -> str:
	"""Who the document belongs to, for the `Sales Executive` line.

	The Sales Team's first row, falling back to the full name of whoever created
	the document. The incumbent site carries this as a Custom Field; Q3 decided we
	derive it instead of adding one.
	"""
	for row in doc.get("sales_team") or []:
		sales_person = cstr(row.get("sales_person")).strip()
		if sales_person:
			return sales_person

	owner = doc.get("owner")
	return cstr(frappe.db.get_value("User", owner, "full_name")) if owner else ""


def yht_creator_contact(doc) -> dict:
	"""`{name, mobile}` for whoever created the document.

	REPLACES the incumbent's `Created By Name` / `Creator Mobile No` Custom Fields.
	Q3: we add no fields — the same two values already exist on `User`, and a
	Custom Field duplicating them is one more thing to keep in step. Both keys are
	`""` when the user is unknown or carries no number.
	"""
	blank = {"name": "", "mobile": ""}

	owner = doc.get("owner") if hasattr(doc, "get") else None
	if not owner:
		return blank

	row = frappe.db.get_value("User", owner, ["full_name", "mobile_no", "phone"], as_dict=True)
	if not row:
		return blank

	return {
		"name": cstr(row.full_name).strip(),
		"mobile": cstr(row.mobile_no).strip() or cstr(row.phone).strip(),
	}


def yht_zatca_qr(doc) -> str:
	"""Base-64 PNG for the ZATCA Phase-1 QR, or `""`.

	`ksa_compliance.jinja.get_zatca_phase_1_qr_for_invoice` returns `None` when
	there is no `ZATCA Phase 1 Business Settings` row for the company, or it is
	Disabled — which is the state this site is in until onboarding (blocked on
	CSR/OTP). The invoice must still print, so this degrades to `""` and the format
	omits the `<img>` entirely rather than emitting a broken one.

	The ImportError is caught too, because a print format is not the place to
	discover that an app is missing.

	🔴 THE TWO PATHS ARE NOT THE SAME. "Not onboarded" is expected and stays
	silent. Anything that RAISES is not expected, and a Saudi tax invoice that
	quietly starts printing without its Phase-1 QR must leave a trace somewhere —
	so everything else is logged and only then degraded.
	"""
	name = doc.get("name") if hasattr(doc, "get") else None
	if not name:
		return ""

	try:
		from ksa_compliance.jinja import get_zatca_phase_1_qr_for_invoice
	except ImportError:
		# ksa_compliance is not on this bench. Expected on yht-test.
		return ""

	try:
		return cstr(get_zatca_phase_1_qr_for_invoice(name))
	except Exception:
		frappe.log_error(
			title="yht_zatca_qr failed",
			message=f"Sales Invoice: {name}\n\n{frappe.get_traceback()}",
		)
		return ""


#: 🔴 The receiving account the client's artefacts actually print, held as a
#: constant so the record is resolved BY IBAN and never by `is_default`. The
#: site's default Bank Account is `Saudi National Bank - KATC`; the artefacts
#: print AL RAJHI. Resolving by the default flag would print the wrong receiving
#: account on a customer-facing quotation — see spec Step 10 / OQ-1.
KATC_BANK_IBAN = "SA6880000139608013397744"


def yht_bank_details() -> dict:
	"""`{bank, iban, account_no}` for the designated receiving account.

	🔴 READ WITH `frappe.db.get_value`, NEVER `frappe.get_doc`. This project denies
	branch users `read` on `Bank Account` on purpose (`setup.py`: it exposes the
	account number and IBAN of every company account and there is no permlevel
	split). `erpnext`'s Bank Account controller calls
	`frappe.has_permission("Bank Account", ptype="read", doc=..., throw=True)`,
	which NO `ignore_permissions` flag suppresses — that already broke the payment
	flow once, and is why `api/payment_assist.py` builds Payment Entries field by
	field. A `frappe.get_doc` here would make every format that carries the bank
	block unprintable for every branch user, with a bare `PermissionError` and no
	message. `frappe.db.get_value` reads the table and never enters the controller.

	Do not "simplify" this by granting the permission instead. Printing ONE
	designated receiving account on a customer-facing quotation is a far narrower
	exposure than handing every branch operator every company account's IBAN in the
	desk UI. The two are not equivalent.

	The values are read LIVE, so the block self-corrects if the client edits the
	record. If nothing matches, all three keys come back empty and the calling
	format renders no block at all — never a half-populated `IBAN` line.
	"""
	blank = {"bank": "", "iban": "", "account_no": ""}

	row = frappe.db.get_value(
		"Bank Account",
		{"iban": KATC_BANK_IBAN},
		["bank", "iban", "bank_account_no"],
		as_dict=True,
	)
	if not row:
		return blank

	return {
		"bank": cstr(row.bank).strip(),
		"iban": cstr(row.iban).strip(),
		"account_no": cstr(row.bank_account_no).strip(),
	}


def _tax_key(row) -> str:
	"""The key ERPNext files a row's tax under: `item_code or item_name`.

	`erpnext/controllers/taxes_and_totals.py::set_item_wise_tax`. Rows sharing one
	key share ONE entry in the map, which is why the amounts are split back out
	below rather than read off per row.
	"""
	return cstr(row.get("item_code") or row.get("item_name"))


def _tax_amount(value):
	"""The amount out of one `item_wise_tax_detail` value, whichever shape it is.

	Two shapes are in the wild and a print format has to survive both:
	`[tax_rate, tax_amount]` (the list form ERPNext wrote for years) and
	`{"tax_rate":…, "tax_amount":…, "net_amount":…}` (the current `ItemWiseTaxDetail`).
	Returns `None` — not 0 — when neither fits, so the caller can tell "no data"
	from "no tax".
	"""
	if isinstance(value, dict):
		if "tax_amount" in value:
			return flt(value.get("tax_amount"))
		return None
	if isinstance(value, list | tuple) and len(value) >= 2:
		return flt(value[1])
	return None


def _tax_account_cache() -> dict:
	"""`account_head` -> is it an `Account` with `account_type == "Tax"`.

	Lives on `frappe.local` for the same reason `_item_ar_cache` does: discarded
	at the end of the request, so a print run does one lookup per distinct
	account head instead of one per tax row.
	"""
	cache = getattr(frappe.local, "yht_tax_account_cache", None)
	if cache is None:
		cache = {}
		frappe.local.yht_tax_account_cache = cache
	return cache


def _is_tax_account(account_head) -> bool:
	"""Does this tax row's account head actually hold TAX?

	🔴 THE MEMBERSHIP TEST FOR THE PER-LINE SPLIT, AND IT IS NOT `charge_type`.
	`set_item_wise_tax` (`erpnext/controllers/taxes_and_totals.py:544-545`) is
	called for EVERY charge type unless the document is consolidated or carries
	`dont_recompute_tax`, and an `Actual` charge is distributed across the lines
	as `item.net_amount * actual / doc.net_total`
	(`taxes_and_totals.py:517-518`). So an `Actual` freight row DOES arrive with
	a populated `item_wise_tax_detail` — keying the split on whether the detail
	exists lets a transport charge into a column headed
	`TAX AMT / مبلغ الضريبة` on a Saudi tax invoice.

	Nor is excluding every `Actual` row correct. Measured on the client's own
	data, both shapes exist and they need opposite answers:

	  - `KSSQ-26-0793` — `Actual` SAR 100.00 on
	    `Transportation and Cargo Expense` (root type Expense, no
	    `account_type`). Freight. Must NOT sit in the VAT column.
	  - `KSIN-26-0092` — `Actual` SAR 1.05 on `200602 - VAT OUTPUT 15%`
	    (`account_type = "Tax"`), and it is the document's ONLY tax row. That IS
	    the VAT. Dropping it would print a 0.00 VAT column on a tax invoice and
	    relabel the tax as `Other Charges`.

	`Account.account_type` separates them and is ERPNext's own answer to the
	question. `frappe.db.get_value`, never `get_doc`: it runs no permission
	check, so a branch user who cannot read `Account` still gets a correct
	invoice — the same reason `yht_bank_details` reads the way it does.

	Unknown or missing account heads answer False, so anything unrecognised
	falls out of the column and is labelled as a charge rather than as tax.
	"""
	head = cstr(account_head)
	if not head:
		return False
	cache = _tax_account_cache()
	if head not in cache:
		cache[head] = (
			cstr(frappe.db.get_value("Account", head, "account_type")) == "Tax"
		)
	return cache[head]


def yht_row_taxes(doc) -> dict:
	"""Tax amount per item row, keyed by the child row's `name`.

	🔴 REPLACES `row_net * document_vat_rate / 100` IN THE TWO TAXED FORMATS. That
	arithmetic is only right when every line carries the same single `On Net Total`
	charge, and it is a customer-facing tax invoice that pays for it being wrong:
	one zero-rated line, a second `On Net Total` charge (the rates add, so every
	row is taxed at the sum), an `Actual` charge (`rate` is 0, so the whole TAX AMT
	column prints `0.00`) or an inclusive tax all produce a column that does not
	add up to the `VAT Amount` printed below it.

	ERPNext has already done this split. Every tax row carries
	`item_wise_tax_detail`, keyed by `item_code or item_name` — read it, and let
	the caller fall back to the arithmetic for the rows this returns nothing for
	(a document saved before the field existed, or an in-memory doc that was never
	calculated).

	Two corrections are applied on the way out:

	1. **Currency.** The stored amounts are multiplied by `conversion_rate` — they
	   are in COMPANY currency, while the format prints document currency.
	2. **An additional discount on `Grand Total`.** `tax_amount_after_discount_amount`
	   carries that reduction; `item_wise_tax_detail` is built before it.

	Both are one proportional factor, so both are handled by scaling the map.

	🔴 THE SCALE IS THE CONTRIBUTING ROWS' OWN TOTAL, NOT `total_taxes_and_charges`.
	A row on a non-tax account — freight, handling — belongs in no line's VAT.
	Scaling onto the document total would spread it across every line and print
	it in a column headed `TAX AMT / مبلغ الضريبة` on a Saudi tax invoice, which
	is a worse answer than the `0.00` the old arithmetic gave. Membership is
	decided by `_is_tax_account`, NOT by `charge_type` and NOT by whether the row
	carries `item_wise_tax_detail` — ERPNext populates that for `Actual` charges
	too, so both of those tests let freight into the VAT column. Only the rows
	that actually contributed to `booked` set the scale; whatever is left over is
	the caller's to label (both taxed formats print it as `Other Charges`). Empty
	dict when there is nothing to read.
	"""
	rows = doc.get("items") or []
	if not rows:
		return {}

	booked: dict = {}
	# The document-currency total of ONLY the tax rows that contributed to
	# `booked`. A charge on a non-tax account contributes nothing and is
	# deliberately left out of both.
	contributing_total = 0.0
	for tax in doc.get("taxes") or []:
		if not _is_tax_account(tax.get("account_head")):
			# Not a tax account — a freight or handling charge. It belongs to no
			# line; the caller labels the remainder `Other Charges`.
			continue
		detail = tax.get("item_wise_tax_detail")
		if isinstance(detail, str):
			try:
				detail = json.loads(detail)
			except ValueError:
				continue
		if not isinstance(detail, dict):
			continue
		contributed = False
		for key, value in detail.items():
			amount = _tax_amount(value)
			if amount is None:
				continue
			booked[cstr(key)] = booked.get(cstr(key), 0.0) + amount
			contributed = True
		if contributed:
			contributing_total += flt(tax.get("tax_amount_after_discount_amount"))

	booked_total = sum(booked.values())
	if not booked_total or not contributing_total:
		# Nothing usable (or a genuinely zero-tax document, where the fallback
		# arithmetic lands on 0.00 anyway). `contributing_total` is checked too:
		# a document old enough to carry `item_wise_tax_detail` but no
		# `tax_amount_after_discount_amount` would otherwise scale by 0 and print
		# a column of 0.00, which is worse than the fallback arithmetic.
		return {}

	scale = contributing_total / booked_total

	# Net per key, so several rows sharing one item code split their single entry
	# in proportion instead of each printing the whole of it.
	net_by_key: dict = {}
	for row in rows:
		net_by_key[_tax_key(row)] = net_by_key.get(_tax_key(row), 0.0) + flt(
			row.get("net_amount") or row.get("amount") or 0
		)

	out: dict = {}
	for row in rows:
		key = _tax_key(row)
		if key not in booked or not row.get("name"):
			continue
		key_net = net_by_key.get(key) or 0
		share = (flt(row.get("net_amount") or row.get("amount") or 0) / key_net) if key_net else 0
		out[row.name] = booked[key] * scale * share

	return out


def yht_item_ar_lines(row_or_item_code, width: int = 14) -> list[str]:
	"""The Arabic item name, pre-broken into lines of at most ``width`` characters.

	🔴 WHY THIS EXISTS. This bench's wkhtmltopdf is the unpatched-Qt build (see the
	app's gotcha 44), and its WebKit will not line-break an RTL run inside a table
	cell — measured every way: `table-layout: fixed`, explicit percentage widths on
	every column, `word-wrap`, `word-break: break-all`, and a fixed-width block. In
	each case a long Arabic name was drawn straight across the Quantity column, and
	`overflow: hidden` only traded the overlap for a clipped name. Names here run to
	66 characters and 71% are past 18, so the column cannot simply be widened.

	Breaking the string in Python removes the decision from the engine: each line is
	emitted separately and there is nothing left to wrap. Returns a LIST rather than
	markup so the template does the joining — no escaping questions, and nothing here
	has to be marked safe.

	Long single words are hard-split rather than allowed to overflow: an item code
	like a 30-character part number has no space to break at.

	⚠️ THE DEFAULT WIDTH IS SET EMPIRICALLY, NOT CALCULATED. A modelled budget did
	not predict this engine: a line measuring 18.4 units overlapped while one
	measuring 20.0 rendered clean, because Arabic shaping makes the glyph advance
	depend on the letters' joining forms rather than on their count. The number below
	is the one that renders correctly across the sixteen documents with the longest
	Arabic names on this site. Re-verify by RENDERING if it is ever changed.
	"""
	text = cstr(yht_item_ar(row_or_item_code)).strip()
	if not text:
		return []

	width = max(cint(width), 8)

	lines, current = [], ""
	for word in text.split():
		while _ar_width(word) > width:
			if current:
				lines.append(current)
				current = ""
			cut = _ar_cut(word, width)
			lines.append(word[:cut])
			word = word[cut:]
		if not current:
			current = word
		elif _ar_width(f"{current} {word}") <= width:
			current = f"{current} {word}"
		else:
			lines.append(current)
			current = word
	if current:
		lines.append(current)
	return lines


#: A Latin letter or digit is materially wider than an Arabic glyph at the same point
#: size, so a budget counted in characters overflows exactly on the rows that mix them.
#: Measured: the rows that still collided after a plain 20-character break were the ones
#: ending in a Latin token — "1 Kg", "3 ملي 6\"". Weighting closes that.
_LATIN_WEIGHT = 1.45


def _ar_width(text: str) -> float:
	"""Approximate rendered width, in Arabic-glyph units."""
	return sum(_LATIN_WEIGHT if ch.isascii() and not ch.isspace() else 1.0 for ch in text)


def _ar_cut(word: str, width: float) -> int:
	"""How many characters of an unbreakable word fit inside the budget."""
	total = 0.0
	for i, ch in enumerate(word):
		total += _LATIN_WEIGHT if ch.isascii() and not ch.isspace() else 1.0
		if total > width:
			return max(i, 1)
	return len(word)
