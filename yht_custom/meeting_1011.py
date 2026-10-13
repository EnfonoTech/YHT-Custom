# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Client meeting 2026-10-11 — the Tuesday batch: rows 17, 20 and 37.

Rows 24, 27, 28, 29 and 36 have their own homes (`form_layout`, `list_type_filter.js`,
`zatca_buyer`, `branch_purchase_order`, `branch_print_format`); these three are
form-and-list layout and live together.

Every step is behind its own `features` switch. This bench serves the client's live
site and UAT off ONE `apps/yht_custom`, so a step that is not gated reaches
production on the next `migrate` of that site — and `yht-khobhar` carries
customisations of its own that this module must never overwrite (see
`yht-client-edits-live-directly`). The rule applied throughout: **a thing the client
already built is adopted, not rebuilt.** Their `Quotation.custom_print_with_arabic`
and the Print Heading they moved to the Quotation front page stay exactly where they
are.

## Row 17 + 34 — ONE tick, not a second button

"Print with Arabic" as a checkbox on the form, on Quotation, Sales Order, Sales
Invoice and Delivery Note, and no second toolbar button for the same thing. The field
is `custom_print_with_arabic` — the name the client's own Quotation field already
has, so their hand-built print formats (`SALES-QUOTATION`, `SALES-INVOICE`, …) can read
`doc.custom_print_with_arabic` on all four without a rename. Saeed's words (1:14:57):
"just share the field name, then we can put it in the print format".

`allow_on_submit` is set on all four: a document is usually printed AFTER it is
submitted, and a tick that can only be changed on a draft answers nothing.

The KATC templates read it through `print_heading.yht_print_lang(doc)`.

## Row 20 — ID first in the Quotation list

`title_field = ""`. Not `"name"`: that one empties the list (see `list_columns`). The
client already did exactly this on Sales Invoice, Delivery Note, Sales Order and
Payment Entry (Property Setters of 2026-09-23/24) and their lists show the ID first;
Quotation is the one they missed.

## Row 37 — Print Heading on the front page

`select_print_heading` is a STANDARD field that ships inside the collapsed
"Printing Settings" section. It moves up beside the dates, and the tick follows it.
The heading is filled in as the document is created (`print_heading_front.js`), so the
operator sees "Delivery Note" become "Delivery Note Return" when they tick Is Return,
instead of finding out at print time.
"""

import frappe
from frappe.utils import cint

from yht_custom import features

ARABIC_TICK = "custom_print_with_arabic"
HEADING = "select_print_heading"

#: The four selling documents (rows 17, 34, 37).
SELLING = ("Quotation", "Sales Order", "Sales Invoice", "Delivery Note")

#: doctype → candidate anchors for the heading + tick, FIRST column of the first tab,
#: tried in order. A candidate that sits behind the item table on this site is
#: skipped: the client re-laid-out the live Delivery Note (its `set_posting_time`
#: is below the items), and "after an anchor" must never mean "onto a different tab".
FRONT_ANCHORS = {
	"Quotation": ("valid_till", "transaction_date"),
	"Sales Order": ("delivery_date", "transaction_date"),
	"Sales Invoice": ("custom_payment_mode", "due_date", "posting_date"),
	"Delivery Note": ("set_posting_time", "posting_date"),
}

_ITEM_TABLE = ("items_section", "items")


# ------------------------------------------------------------------- helpers


def _live_order(doctype: str) -> list:
	return [f.fieldname for f in frappe.get_meta(doctype).fields]


def _front_boundary(order: list) -> int:
	"""Index where the item table begins — everything before it is 'the front'."""
	hits = [order.index(name) for name in _ITEM_TABLE if name in order]
	return min(hits) if hits else len(order)


def _front_anchor(doctype: str, order: list):
	boundary = _front_boundary(order)
	for candidate in FRONT_ANCHORS.get(doctype, ()):
		if candidate in order and order.index(candidate) < boundary:
			return candidate
	return None


def place_after(doctype: str, fieldname: str, anchor: str) -> bool:
	"""Move `fieldname` to sit immediately after `anchor`. Returns whether it moved.

	Only ever REORDERS the live meta order, so the result is a permutation by
	construction. Writes the whole order (the base is `meta.fields`, never the stored
	Property Setter — see `field_layout._apply_field_order` for the three days that
	cost). Idempotent: a field already directly after its anchor is left alone.
	"""
	from yht_custom.field_layout import _read_order, _write_order

	order = _live_order(doctype)
	if fieldname not in order or anchor not in order:
		return False
	if order.index(fieldname) == order.index(anchor) + 1:
		return False
	target = list(order)
	target.remove(fieldname)
	target.insert(target.index(anchor) + 1, fieldname)
	if sorted(target) != sorted(order):  # pragma: no cover - construction guarantees it
		return False
	ps_name, _stored = _read_order(doctype)
	_write_order(doctype, ps_name, target)
	return True


# ----------------------------------------------------------- row 37 — heading


def setup_heading_front() -> dict:
	"""Row 37 — bring `select_print_heading` to the front page. Idempotent."""
	if not features.enabled("oct11_r37_print_heading_front"):
		return {"skipped": "oct11_r37_print_heading_front is off for this site"}

	moved, skipped = [], []
	for doctype in SELLING:
		if not frappe.db.exists("DocType", doctype):
			continue
		order = _live_order(doctype)
		if HEADING not in order:
			skipped.append(f"{doctype}: no {HEADING}")
			continue
		boundary = _front_boundary(order)
		if order.index(HEADING) < boundary:
			# Already on the front page — the client did this themselves on the live
			# Quotation. Adopted, not moved.
			continue
		anchor = _front_anchor(doctype, order)
		if not anchor:
			skipped.append(f"{doctype}: no front-page anchor on this site")
			continue
		if place_after(doctype, HEADING, anchor):
			moved.append(doctype)
			# The tick belongs directly under the heading, whichever step ran first —
			# otherwise it converges only on the SECOND migrate.
			if ARABIC_TICK in _live_order(doctype):
				place_after(doctype, ARABIC_TICK, HEADING)
	if skipped:
		frappe.log_error(message="\n".join(skipped), title="yht_custom: heading front")
	return {"moved": moved, "skipped": skipped}


# ------------------------------------------------------- row 17 / 34 — the tick


def setup_print_with_arabic() -> dict:
	"""Rows 17 + 34 — the Print With Arabic tick on all four selling documents."""
	if not features.enabled("oct11_r17_print_with_arabic"):
		return {"skipped": "oct11_r17_print_with_arabic is off for this site"}

	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	created, adopted = [], []
	to_create = {}
	for doctype in SELLING:
		if not frappe.db.exists("DocType", doctype):
			continue
		existing = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": ARABIC_TICK}, "name")
		if existing:
			# The client's own (Quotation, live). Keep it — only make it tickable
			# after submit, which is when a document is actually printed.
			if not cint(frappe.db.get_value("Custom Field", existing, "allow_on_submit")):
				frappe.db.set_value("Custom Field", existing, "allow_on_submit", 1)
				frappe.clear_cache(doctype=doctype)
			adopted.append(doctype)
			continue
		order = _live_order(doctype)
		anchor = HEADING if HEADING in order else (_front_anchor(doctype, order) or "naming_series")
		to_create[doctype] = [
			{
				"fieldname": ARABIC_TICK,
				"label": "Print With Arabic",
				"fieldtype": "Check",
				"insert_after": anchor,
				"allow_on_submit": 1,
				"print_hide": 1,
				"no_copy": 0,
				"description": "Tick to print this document with the Arabic columns / names.",
			}
		]
		created.append(doctype)
	if to_create:
		create_custom_fields(to_create, ignore_validate=True)

	placed = []
	for doctype in SELLING:
		if not frappe.db.exists("DocType", doctype):
			continue
		order = _live_order(doctype)
		if ARABIC_TICK not in order or HEADING not in order:
			continue
		# Directly under the heading when the heading is on the front page; where it
		# is not (a site that has not run row 37), the tick keeps its own anchor.
		if order.index(HEADING) < _front_boundary(order) and place_after(doctype, ARABIC_TICK, HEADING):
			placed.append(doctype)
	return {"created": created, "adopted": adopted, "placed": placed}


# ------------------------------------------------------------- row 20 — the ID


def setup_quotation_id_first() -> dict:
	"""Row 20 — `Quotation.title_field = ""`, so the list's first column is the ID.

	Clearing the title field removes the Title column, and the Quotation list had no other
	column carrying the customer (only Date, Grand Total, Status) — the client's UAT round
	(2026-10-13) reported "ID is showing first but Title column is not appearing". The
	customer's name is therefore made an ordinary list column, directly after the ID, using
	the same two levers as `list_columns`: `in_list_view` so the column exists and a List
	View Settings row to order it.
	"""
	if not features.enabled("oct11_r20_quotation_id_first"):
		return {"skipped": "oct11_r20_quotation_id_first is off for this site"}
	if not frappe.db.exists("DocType", "Quotation"):
		return {}

	import json

	from yht_custom.form_layout import _set_property
	from yht_custom.list_columns import STATUS_INDICATOR, _write_list_view_settings

	_set_property("Quotation", None, "title_field", "", "Data", for_doctype=True)

	meta = frappe.get_meta("Quotation")
	if meta.get_field("customer_name"):
		# The column only exists as a candidate when it is `in_list_view`.
		_set_property("Quotation", "customer_name", "in_list_view", "1", "Check")

	# 🔴 A List View Settings row the client (or an admin) already made is THEIR column set —
	# the live Quotation list carries eight of them (ID, Status, Customer Name, Date, Total,
	# Mobile, Contact …). Only a site with no row gets our default; a row that lacks the
	# customer name gets it inserted after the first column; anything else is left alone.
	columns = ["customer_name", "transaction_date", STATUS_INDICATOR, "grand_total"]
	raw = frappe.db.get_value("List View Settings", "Quotation", "fields")
	if not raw:
		_write_list_view_settings("Quotation", [c for c in columns if c == STATUS_INDICATOR or meta.get_field(c)])
		action = "default columns written"
	else:
		entries = json.loads(raw)
		if any(e.get("fieldname") == "customer_name" for e in entries):
			action = "existing columns kept"
		else:
			entries.insert(min(1, len(entries)), {"fieldname": "customer_name", "label": meta.get_label("customer_name") or "Customer Name"})
			frappe.db.set_value("List View Settings", "Quotation", "fields", json.dumps(entries))
			action = "customer_name inserted into existing columns"

	frappe.clear_cache(doctype="Quotation")
	return {"Quotation": {"title_field": "cleared", "columns": action}}


# ------------------------------------------------------ row 22 — Other Remarks


#: doctype → candidate anchors on the FRONT page for `custom_other_remarks`. The field is
#: created beside `remarks`, which on these three sits at the bottom of the collapsed
#: "Additional Info" section of the More Info tab (Sales Invoice: field 223 of 225), so the
#: client's UAT round reported it "missing". Purchase Order is created at the front already.
OTHER_REMARKS_FRONT_ANCHORS = {
	"Sales Invoice": ("po_date", "po_no", "company"),
	"Purchase Invoice": ("company", "supplier_name"),
	"Purchase Receipt": ("supplier_delivery_note", "supplier_name"),
}


def setup_other_remarks_front() -> dict:
	"""Row 22 — bring Other Remarks to the front page of SI / PI / PR. Idempotent."""
	if not features.enabled("oct11_r22_other_remarks_front"):
		return {"skipped": "oct11_r22_other_remarks_front is off for this site"}

	from yht_custom.other_remarks import FIELDNAME

	moved, skipped = [], []
	for doctype, candidates in OTHER_REMARKS_FRONT_ANCHORS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		order = _live_order(doctype)
		if FIELDNAME not in order:
			skipped.append(f"{doctype}: no {FIELDNAME}")
			continue
		boundary = _front_boundary(order)
		if order.index(FIELDNAME) < boundary:
			continue  # already on the front page
		anchor = next((c for c in candidates if c in order and order.index(c) < boundary), None)
		if not anchor:
			skipped.append(f"{doctype}: no front-page anchor on this site")
			continue
		if place_after(doctype, FIELDNAME, anchor):
			moved.append(doctype)
	if skipped:
		frappe.log_error(message="\n".join(skipped), title="yht_custom: other remarks front")
	return {"moved": moved, "skipped": skipped}
