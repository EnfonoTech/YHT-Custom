# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""CR-004 / CR-005 — one print format per doctype, the variant chosen at print time.

## What the client asked for

"we don't need a separate print format for each one — give it as a tick option
instead". Three axes were named: **Arabic or not**, **letterhead or not**, and
**which heading** the page carries (Quotation vs Proforma, Delivery Note vs
Delivery Note Return).

## What was already there, measured before building anything

Two of the three axes are native and were already working, which is why this
module is small:

* **Letterhead** — the print dialog's own Letter Head picker. Every KATC template
  already branches on `letter_head` / `no_letterhead`; that branch is what fixed
  the blank first page in September and it is not touched here.
* **Heading** — `select_print_heading` is a STANDARD ERPNext field, present on
  Quotation, Sales Order, Sales Invoice, Delivery Note, Purchase Invoice and
  Purchase Order, and already `allow_on_submit = 1` on all of them. The client is
  ALREADY USING IT: on `yht-khobhar` 2026-09-26, 1,906 of 1,964 Delivery Notes,
  2,369 of 3,614 Purchase Invoices and 1,108 of 2,481 Sales Invoices carry one.
  Quotation, Sales Order and Purchase Order carry none — those are the gaps.

So CR-005 ("bulk-editable Print Heading for Return vs Normal Delivery Note") needs
NO new field and no new bulk tool: `allow_on_submit` is exactly what makes a field
appear in the list view's Edit dialog, and `form_layout.setup_return_split_filter`
already ships the filtered Return / Normal lists to run it from. What was missing
is that the KATC templates ignored the field and printed a hardcoded title.

## What this module adds

1. `select_print_heading` is FILLED on save when blank, from the document itself —
   a return gets the return heading. Nobody has to remember, and the bulk edit
   CR-005 asks for becomes a correction rather than data entry.
2. A heading prints BILINGUALLY. `Print Heading` is a bare naming doctype with one
   field, so the Arabic lives in `ARABIC` below rather than on the record.
3. The Arabic column follows the print dialog's LANGUAGE selector instead of a
   separate Print Format record, which is what collapses two formats into one.

🔴 THE ARABIC MAP IS NOT A TRANSLATION LAYER. `_()` is not used and must not be:
these are the exact document titles the client's incumbent system printed, they
are what customers and the tax authority recognise, and routing them through
translation would let an unrelated `.csv` change what a tax invoice calls itself.
"""

import frappe
from frappe.utils import cint, cstr

from yht_custom import features

#: Heading → the Arabic that prints beneath it. Keys that already exist as
#: `Print Heading` records on the live site are spelled to match them EXACTLY,
#: because `select_print_heading` is a Link and a near-miss creates a second
#: record rather than reusing theirs.
ARABIC = {
	"Sales Quotation": "عرض سعر",
	# `custom_print_as` on Sales Order offers the bare word, and 1,296 documents
	# already carry it — the alias is what keeps that Select working against the
	# `Print Heading` record, which is named "Sales Quotation".
	"Quotation": "عرض سعر",
	"Proforma Invoice": "فاتورة مبدئية",
	"Sales Order": "أمر بيع",
	"Sales Invoice": "فاتورة ضريبية",
	"Sales Return": "مرتجع مبيعات",
	"Credit Note": "إشعار دائن",
	"Debit Note": "إشعار مدين",
	"Delivery Note": "مذكرة تسليم",
	"Delivery Note Return": "مرتجع تسليم",
	"Purchase Invoice": "فاتورة مشتريات",
	"Purchase Return": "مرتجع مشتريات",
	"Purchase Order": "أمر شراء",
	"Expenses Invoice": "فاتورة مصروفات",
	"Receipt Voucher": "سند قبض",
	"Payment Voucher": "سند صرف",
	# CR-004 offers this as a `Print As` option on Purchase Order, so it needs a
	# Print Heading record and an Arabic twin like every other title.
	"Purchase Enquiry": "طلب عرض سعر",
}

#: Heading → what the PAGE says, where the two differ. The record is named for the
#: list it has to be unambiguous in; the print says what the client's incumbent
#: system said, because that is the word their customers recognise.
EN_DISPLAY = {
	"Sales Quotation": "QUOTATION",
	"Quotation": "QUOTATION",
	# 🔴 A KSA SALES INVOICE PRINTS AS A TAX INVOICE, and the artefact the client
	# signed off on says so. The `Print Heading` record has to be named "Sales
	# Invoice" because that is the one already on 1,108 documents here, but the
	# page must not start calling itself something the tax authority does not
	# recognise. A RETURN still resolves to Credit Note and prints CREDIT NOTE.
	"Sales Invoice": "TAX INVOICE",
}


def english(heading: str) -> str:
	"""The upper-case English title for a heading."""
	return (EN_DISPLAY.get(heading) or cstr(heading)).upper()


#: doctype → (forward heading, return heading). The return slot is `None` where the
#: doctype cannot be a return.
DEFAULTS = {
	"Quotation": ("Sales Quotation", None),
	"Sales Order": ("Sales Order", None),
	"Sales Invoice": ("Sales Invoice", "Credit Note"),
	"Delivery Note": ("Delivery Note", "Delivery Note Return"),
	"Purchase Invoice": ("Purchase Invoice", "Debit Note"),
	"Purchase Order": ("Purchase Order", None),
}

#: CR-004's "tick option" for the documents that print under more than one name.
#: Sales Order already carries this field and 1,296 documents use it; Quotation and
#: Purchase Order get the same shape rather than a second mechanism.
PRINT_AS = {
	"Sales Order": ("Sales Order", "Quotation", "Proforma Invoice"),
	"Quotation": ("Sales Quotation", "Proforma Invoice"),
	"Purchase Order": ("Purchase Order", "Purchase Enquiry"),
}

FIELDNAME = "custom_print_as"

#: CR-004 acceptance #4 — "some teams need an extra item-column note; it must be
#: independently toggleable without becoming its own format."
#:
#: 🔴 A SECOND LINE IN THE ITEM CELL, NOT A SEVENTH COLUMN. Every KATC item table
#: pins each column's width and the set must sum to 100% — the comment above each
#: one says so, and it is what stopped the Arabic spilling over the Quantity
#: figures. A new column would need a third width set per template and re-verified
#: page counts for a toggle that is off by default. The note renders under the item
#: name, which is the same idiom the Delivery Note and Tax Invoice already use for
#: the Arabic name, and cannot disturb the widths at all.
ITEM_NOTE_FIELD = "custom_print_item_note"


# ------------------------------------------------------------------ resolution


def default_heading(doc) -> str:
	"""The heading this document would carry if nobody chose one."""
	forward, returned = DEFAULTS.get(doc.doctype, (None, None))
	if returned and cint(doc.get("is_return")):
		return returned
	# An expense Purchase Invoice is an Expenses Invoice, which is the client's own
	# name for it and already a Print Heading record here.
	if doc.doctype == "Purchase Invoice" and cint(doc.get("custom_is_expense_invoice")):
		return "Expenses Invoice"
	return forward or ""


def set_print_heading(doc, method=None):
	"""`before_save` — fill a blank `select_print_heading`.

	Only ever fills a BLANK. A heading somebody chose is a decision, and the whole
	point of CR-005 is that the choice can be corrected in bulk afterwards; a
	handler that re-derived it on every save would undo that bulk edit the next
	time the document was touched.

	Behind the switch: this writes a stored field on six doctypes on a bench that
	also serves the client's live site.
	"""
	if not features.enabled("cr_004_print_heading"):
		return
	if not doc.meta.has_field("select_print_heading"):
		return
	if cstr(doc.get("select_print_heading")).strip():
		return

	heading = default_heading(doc)
	if heading and frappe.db.exists("Print Heading", heading):
		doc.select_print_heading = heading


#: 🔴 WHAT THE PAGE SAID BEFORE CR-004, BYTE FOR BYTE — including the RLM marks
#: and the non-breaking space inside each Arabic title.
#:
#: This exists because the templates live on a SHARED BENCH. `apps/yht_custom` is
#: one directory serving the client's live site and UAT, and a template is read
#: from disk on every render — so the moment this work is pulled, the live
#: quotation print changes unless something stops it. `yht_print_heading` returns
#: these until `cr_004_print_heading` is on for the site, which makes the live
#: prints identical to what the client signed off on in September and makes the
#: switch, not the deploy, the moment the change takes effect.
#:
#: The Quotation entry is deliberately a single line with no Arabic twin: the old
#: markup was ONE `katc-title` div reading "Quotation / عرض سعر", not a pair.
#: Keyed by the template's OWN identity, not by `doc.doctype`: `proforma_invoice.html`
#: renders a **Quotation** document under a Proforma Invoice title, so the doctype
#: alone cannot tell the two apart. Each template passes its own key.
LEGACY_TITLES = {
	"Quotation": ("Quotation / ‏عرض سعر‏", ""),
	"Proforma Invoice": ("PROFORMA INVOICE", "فاتورة مبدئية"),
	"Sales Order": ("SALES ORDER", "أمر بيع"),
	"Delivery Note": ("DELIVERY NOTE", "مذكرة تسليم"),
	"Sales Invoice": ("TAX INVOICE", "فاتورة ضريبية"),
	"Purchase Order": ("PURCHASE ORDER", "أمر شراء"),
}


def yht_print_heading(doc, as_kind: str | None = None) -> dict:
	"""`{en, ar}` for the title block. A jinja method — see hooks.py.

	Resolution order, most specific first:

	1. `select_print_heading` — what the operator chose, editable after submit and
	   in bulk, which is CR-004's "tick option" and CR-005's whole requirement
	2. `custom_print_as` — the Select that lets ONE Sales Order print as a
	   Quotation or a Proforma Invoice
	3. the doctype's own default, return-aware

	Never empty for a doctype in `DEFAULTS`: a print with no title is a worse
	outcome than a title that is merely generic.
	"""
	if not features.enabled("cr_004_print_heading"):
		legacy = LEGACY_TITLES.get(as_kind or getattr(doc, "doctype", ""))
		if legacy:
			return {"en": legacy[0], "ar": legacy[1], "heading": ""}

	# 🔴 `as_kind` OUTRANKS EVERYTHING, INCLUDING `select_print_heading`, AND THAT
	# ORDER WAS WRONG ONCE. It is the TEMPLATE naming itself: `proforma_invoice.html`
	# is reached only by choosing the Proforma print format, which is a more
	# specific statement than any value stored on the document. With the stored
	# field winning, the backfill that stamped "Sales Quotation" onto 2,726
	# quotations made every Proforma print say QUOTATION — caught on UAT.
	if as_kind:
		chosen = as_kind
	else:
		chosen = ""
		if hasattr(doc, "get"):
			chosen = cstr(doc.get("select_print_heading")).strip() or cstr(doc.get(FIELDNAME)).strip()
		if not chosen:
			chosen = default_heading(doc)

	return {"en": english(chosen), "ar": ARABIC.get(chosen, ""), "heading": chosen}


def yht_item_note(row) -> str:
	"""The line's own description, when it says something the item name does not.

	Returns `""` unless the note adds information: ERPNext copies `item_name` into
	`description` on most rows, and printing the same words twice under themselves
	is worse than printing nothing. HTML is stripped — `description` is a Text
	Editor field and a pasted `<div>` would reach the page as markup.
	"""
	from frappe.utils import strip_html

	if not row:
		return ""
	note = cstr(strip_html(cstr(row.get("description")))).strip()
	name = cstr(row.get("item_name")).strip()
	if not note or note == name or note == cstr(row.get("item_code")).strip():
		return ""
	return note


def yht_feature(name: str) -> bool:
	"""Is a feature switch on for this site? For use inside a print template.

	🔴 A TEMPLATE IS SHARED DISK, SO EVEN ITS CSS IS A PRODUCTION CHANGE. The
	CR-004 work added three things to the KATC templates — a `direction: ltr`
	pin, a `.katc-note` rule and the item-note span — all of which only do
	anything when this feature is on. All three still changed the rendered BYTES
	on the client's live site the moment the branch was pulled, and the
	before/after hash check caught four formats moving.

	Guarding them in Python would not have helped: the markup is in the template,
	so the template has to be able to ask.

	Never raises — a print that 500s because a switch name is wrong is worse than
	one that renders the pre-CR-004 page.
	"""
	try:
		return features.enabled(name)
	except Exception:
		return False


def yht_print_lang() -> str:
	"""`"ar"` when the print dialog asked for Arabic, else `"en"`.

	🔴 THIS IS WHAT REPLACES A SECOND PRINT FORMAT. `printview` sets
	`frappe.local.lang` from the dialog's `_lang`, so the language selector the
	desk already shows becomes the Arabic tick the client asked for, and the
	`… Arabic` shim records stop being the only way to reach that layout.

	Read defensively: a template rendered outside a request — a test, a scheduled
	PDF — has no `frappe.local.lang` worth trusting, and English is the safe
	answer for a document that may be going to a bank.
	"""
	if not features.enabled("cr_004_print_heading"):
		# The Arabic column stays where it was — on the "… Arabic" shim records —
		# until the switch is on. Same reason as `LEGACY_TITLES`.
		return "en"

	try:
		lang = cstr(getattr(frappe.local, "lang", "") or "")
	except Exception:
		return "en"
	return "ar" if lang.lower().startswith("ar") else "en"


# --------------------------------------------------------------------- setup


def setup_print_headings() -> dict:
	"""Provision the Print Heading records and the `Print As` Selects. Idempotent."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	created = []
	for heading in ARABIC:
		if not frappe.db.exists("Print Heading", heading):
			frappe.get_doc({"doctype": "Print Heading", "print_heading": heading}).insert(
				ignore_permissions=True
			)
			created.append(heading)

	note_fields = {}
	for doctype in DEFAULTS:
		if frappe.db.exists("DocType", doctype):
			note_fields[doctype] = [
				{
					"fieldname": ITEM_NOTE_FIELD,
					"label": "Print Item Notes",
					"fieldtype": "Check",
					"insert_after": "select_print_heading",
					"allow_on_submit": 1,
					"description": "Print each line's description under the item name. Off by default.",
				}
			]
	if note_fields:
		create_custom_fields(note_fields, ignore_validate=True)

	fields = {}
	for doctype, options in PRINT_AS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		anchor = "order_type" if frappe.get_meta(doctype).get_field("order_type") else "select_print_heading"
		if not frappe.get_meta(doctype).get_field(anchor):
			continue
		fields[doctype] = [
			{
				"fieldname": FIELDNAME,
				"label": "Print As",
				"fieldtype": "Select",
				"options": "\n".join(options),
				"default": options[0],
				"insert_after": anchor,
				# The client prints a submitted document under a different name; a
				# field they cannot change after submit would not answer CR-004.
				"allow_on_submit": 1,
				"description": "Which document this prints as. Changeable after submit.",
			}
		]
	if fields:
		create_custom_fields(fields, ignore_validate=True)

	# 🔴 `select_print_heading` MUST BE VISIBLE TO BE BULK-EDITABLE (CR-005). The
	# list view's Edit dialog offers `allow_on_submit` fields that are not hidden;
	# upstream ships this one inside the collapsed "Printing Settings" section,
	# which is reachable but is not what "bulk edit the Return notes" means.
	# `in_standard_filter` is what puts it in the list sidebar beside the existing
	# Return / Normal split.
	from yht_custom.form_layout import _set_property

	for doctype in DEFAULTS:
		if frappe.db.exists("DocType", doctype):
			_set_property(doctype, "select_print_heading", "in_standard_filter", "1", "Check")

	return {"headings_created": created, "print_as": sorted(fields), "item_note": sorted(note_fields)}


def backfill_headings(commit: bool = False) -> dict:
	"""Stamp the derived heading onto documents that have none — CR-005's other half.

	    bench --site … execute yht_custom.print_heading.backfill_headings --kwargs "{'commit': True}"

	`db.set_value` with `update_modified=False`: these are submitted documents and
	a heading is a printing preference, not a change to the transaction.
	"""
	filled, per_doctype = 0, {}

	for doctype in DEFAULTS:
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		# Every field `default_heading` reads has to be SELECTED, or a return reads
		# as a forward document and the backfill stamps the wrong title on it.
		fields = ["name"] + [
			f for f in ("is_return", "custom_is_expense_invoice") if meta.get_field(f)
		]
		rows = frappe.get_all(
			doctype,
			# 🔴 `["in", ["", None]]` DOES NOT MATCH NULL. SQL's `IN` compares with `=`,
			# and `x = NULL` is NULL, not true — so the first run of this filled 18
			# rows out of thousands and looked like it had nothing to do. `["is",
			# "not set"]` is the frappe filter that becomes `ifnull(field, '') = ''`.
			filters={"select_print_heading": ["is", "not set"], "docstatus": ["<", 2]},
			fields=fields,
			limit=0,
		)
		count = 0
		for row in rows:
			heading = default_heading(frappe._dict(row, doctype=doctype))
			if not heading or not frappe.db.exists("Print Heading", heading):
				continue
			if commit:
				frappe.db.set_value(doctype, row.name, "select_print_heading", heading, update_modified=False)
			count += 1
		per_doctype[doctype] = count
		filled += count

	if commit:
		frappe.db.commit()

	summary = {"committed": bool(commit), "filled": filled, "per_doctype": per_doctype}
	print(frappe.as_json(summary, indent=1))
	return summary
