# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Client meeting 2026-10-11 — the Wednesday batch: provisioning for rows 13 and 30.

Row 26 lives in `session_year`, row 32 in `doc_number_search`, row 33 in
`expense_invoice`, row 35 in `print_consolidation`.

Both steps are behind their own `features` switch, create nothing but Custom Fields (by
`create_custom_fields`, never as fixtures — a fixture reaches the live site on its next
migrate unconditionally) and Property Setters, never commit (`after_migrate` commits per
step) and never delete.

## Row 13 — a Valuation Rate column in the item grid

`Sales Invoice Item` has no `valuation_rate` and the standard one on Quotation / Sales
Order Item is filled from a Bin that is not branch-scoped, so there is no uniform column to
expose. `custom_valuation_rate` is a new read-only, `print_hide` Currency on all four item
doctypes, fed by the branch-scoped `price_assist.get_valuation_rates`.

🔴 The grid has an eleven-unit budget (gotcha 52) and it is already full, so this step also
re-sets every width: item 2, qty 1, uom 1, discount 1, rate 2, valuation 1, amount 1, stock 1
= 10. Sales Order Item was ALREADY over budget (ERPNext's `delivery_date` takes two units and
is not in `sales_assist.GRID_LAYOUT`), so `delivery_date` leaves its grid.

## Row 30 — address, contact, PO and sales team on the front page

One `Address & Contact` section (and, where the document has a sales team, one collapsed
`Sales Team` section) is placed immediately before the item table. No new DATA field
anywhere: the fields only move.
"""

import frappe

from yht_custom import features
from yht_custom.field_layout import _read_order, _write_order
from yht_custom.meeting_1011 import SELLING, _front_boundary, _live_order, place_after

ITEM_DOCTYPES = ("Quotation Item", "Sales Order Item", "Sales Invoice Item", "Delivery Note Item")

VALUATION = "custom_valuation_rate"

#: fieldname -> width, summing to 10 (+1 start = the grid's 11).
GRID_WIDTHS = (
	("item_code", 2),
	("qty", 1),
	("uom", 1),
	("discount_percentage", 1),
	("rate", 2),
	(VALUATION, 1),
	("amount", 1),
	("actual_qty", 1),
)

#: candidate anchors for `po_no` / `po_date` when they sit behind the item table (the live
#: Sales Invoice has them in More Info), first present one BEFORE the boundary wins.
#: Mirrors `meeting_1011.FRONT_ANCHORS`.
PO_ANCHORS = ("tax_id", "customer_name", "customer")

PARTY_SECTION = "custom_front_party_section"
PARTY_COLUMN = "custom_front_party_col"
TEAM_SECTION = "custom_front_team_section"

BLOCK_A = [PARTY_SECTION, "customer_address", "address_display", PARTY_COLUMN, "contact_person", "contact_display"]
BLOCK_B = [TEAM_SECTION, "sales_team"]


# ------------------------------------------------------------------ row 13


def setup_valuation_column() -> dict:
	"""Row 13 — `custom_valuation_rate` on the four item doctypes and the grid widths."""
	if not features.enabled("oct11_r13_sales_history"):
		return {"skipped": "oct11_r13_sales_history is off for this site"}

	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	from yht_custom.form_layout import _set_property

	existing = [dt for dt in ITEM_DOCTYPES if frappe.db.exists("DocType", dt)]
	create_custom_fields(
		{
			dt: [
				{
					"fieldname": VALUATION,
					"label": "Valuation Rate",
					"fieldtype": "Currency",
					"options": "Company:company:default_currency",
					"read_only": 1,
					"print_hide": 1,
					"no_copy": 0,
					"allow_on_submit": 0,
					"in_list_view": 1,
					"columns": 1,
					"insert_after": "rate",
				}
			]
			for dt in existing
		},
		ignore_validate=True,
	)

	placed = []
	for dt in existing:
		frappe.clear_cache(doctype=dt)
		# A `field_order` Property Setter (Sales Invoice Item has one) ignores `insert_after`.
		if place_after(dt, VALUATION, "rate"):
			placed.append(dt)
		meta = frappe.get_meta(dt, cached=False)
		for fieldname, width in GRID_WIDTHS:
			if fieldname != VALUATION and meta.get_field(fieldname):
				_set_property(dt, fieldname, "columns", str(width), "Int")
				_set_property(dt, fieldname, "in_list_view", "1", "Check")
		if dt == "Sales Order Item" and meta.get_field("delivery_date"):
			# The header carries the date; two units cannot fit.
			_set_property(dt, "delivery_date", "in_list_view", "0", "Check")
		frappe.clear_cache(doctype=dt)
	return {"doctypes": existing, "placed": placed}


# ------------------------------------------------------------------ row 30


def _is_section_break(doctype: str, fieldname: str) -> bool:
	df = frappe.get_meta(doctype).get_field(fieldname)
	if df:
		return df.fieldtype == "Section Break"
	return fieldname.startswith("section_break")


def _block_target(doctype: str, order: list):
	"""The field the front block goes IMMEDIATELY BEFORE.

	The boundary field (the item table), or the Section Break just before it. The live
	Delivery Note is laid out `… po_date, section_break1, items`: `section_break1` heads the
	item table, so inserting between it and `items` would drop the block INSIDE the items
	section.
	"""
	boundary = _front_boundary(order)
	if boundary >= len(order):
		return None
	if boundary > 0 and _is_section_break(doctype, order[boundary - 1]):
		return order[boundary - 1]
	return order[boundary]


def place_block(doctype: str, fieldnames: list, before: str) -> bool:
	"""Move `fieldnames` (in the given order) to sit immediately before `before`.

	Built from the live meta order (gotcha 111) and only ever a REORDER, so the result is a
	permutation by construction. Idempotent: a block already contiguous and directly before
	its target writes nothing. Returns whether it wrote.
	"""
	order = _live_order(doctype)
	block = [name for name in fieldnames if name in order]
	if not block or before not in order or before in block:
		return False
	rest = [name for name in order if name not in block]
	target = rest[: rest.index(before)] + block + rest[rest.index(before) :]
	if target == order or sorted(target) != sorted(order):
		return False
	ps_name, _stored = _read_order(doctype)
	_write_order(doctype, ps_name, target)
	return True


def setup_front_details() -> dict:
	"""Row 30 — address, contact, PO and sales team on the front page. Idempotent."""
	if not features.enabled("oct11_r30_front_details"):
		return {"skipped": "oct11_r30_front_details is off for this site"}

	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	doctypes = [dt for dt in SELLING if frappe.db.exists("DocType", dt)]

	fields = {}
	for dt in doctypes:
		has_team = bool(frappe.get_meta(dt).get_field("sales_team"))
		layout = [
			{
				"fieldname": PARTY_SECTION,
				"label": "Address & Contact",
				"fieldtype": "Section Break",
				"insert_after": "customer_address",
			},
			{
				"fieldname": PARTY_COLUMN,
				"fieldtype": "Column Break",
				"insert_after": "address_display",
			},
		]
		if has_team:
			layout.append(
				{
					"fieldname": TEAM_SECTION,
					"label": "Sales Team",
					"fieldtype": "Section Break",
					"collapsible": 1,
					"insert_after": "sales_team",
				}
			)
		fields[dt] = layout
	create_custom_fields(fields, ignore_validate=True)

	placed, po_moved = [], []
	for dt in doctypes:
		frappe.clear_cache(doctype=dt)
		# PO number / date first, so the block lands against the final front page.
		if _pull_po_fields(dt):
			po_moved.append(dt)
		order = _live_order(dt)
		before = _block_target(dt, order)
		if not before:
			continue
		# One contiguous block: address + contact, then the team section where there is one.
		block = BLOCK_A + (BLOCK_B if TEAM_SECTION in order else [])
		if place_block(dt, block, before):
			placed.append(dt)
	return {"placed": placed, "po_moved": po_moved}


def _pull_po_fields(doctype: str) -> bool:
	"""`po_no`, `po_date` onto the front page where they sit behind the item table."""
	order = _live_order(doctype)
	if "po_no" not in order:
		return False
	boundary = _front_boundary(order)
	if order.index("po_no") < boundary and ("po_date" not in order or order.index("po_date") < boundary):
		return False  # already front — adopted as is
	anchor = next((a for a in PO_ANCHORS if a in order and order.index(a) < boundary), None)
	if not anchor:
		return False
	moved = place_after(doctype, "po_no", anchor)
	if "po_date" in _live_order(doctype):
		moved = place_after(doctype, "po_date", "po_no") or moved
	return moved
