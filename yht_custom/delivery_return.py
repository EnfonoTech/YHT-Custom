# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Delivery return raised FROM a credit note.

The site's standing rule runs the other way: `return_flow.enforce_return_stock_route`
insists that a return of DELIVERED goods is raised on the Delivery Note, and the
credit note follows. Some branches work credit-note-first, so this module adds the
reverse route — gated by `YHT Return Settings`, off by default.

The chain it has to reconstruct, and every link is already in the data:

    Delivery Note ─► Sales Invoice ─► Sales Return ─► [Create] ─► Delivery Return

* the credit-note row carries `sales_invoice_item` — the ORIGINAL invoice row it
  reverses. ERPNext's own return mapper writes it, and
  `return_flow.RETURN_ROW_LINK` already depends on it being there.
* that invoice row carries `delivery_note` and `dn_detail` — the delivery note that
  shipped the goods, and the row on it.

So the delivery return is `return_against` the ORIGINAL delivery note (which is what
ERPNext's over-return guard counts against) while each row also points back at the
credit note through `against_sales_invoice` / `si_detail`. Both connections exist,
in the fields ERPNext itself uses, so no custom link field is needed.

🔴 ALL OR NOTHING, for the same reason `link_credit_note_to_original_invoice` is.
ERPNext's over-return guard (`validate_returned_items`) keys on the ROW link. A
delivery return whose rows do not carry `dn_detail` can post any quantity, so a
partially-resolved document is worse than none: either every row walks back to one
delivery note, or nothing is created and the operator is told which row broke the
chain.
"""

import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import cint, cstr, flt

from yht_custom.yht_custom.doctype.yht_return_settings.yht_return_settings import (
	allow_delivery_note_from_sales_return,
)


def _resolve_rows(credit_note):
	"""``(delivery_note, {credit_row: (dn_row, warehouse)}, unresolved_idx)``.

	One query per hop rather than per row — this runs on a document that can carry a
	hundred lines.
	"""
	rows = credit_note.get("items") or []
	invoice_rows = {cstr(r.get("sales_invoice_item")) for r in rows if r.get("sales_invoice_item")}

	source = {}
	if invoice_rows:
		for r in frappe.get_all(
			"Sales Invoice Item",
			filters={"name": ("in", list(invoice_rows))},
			fields=["name", "delivery_note", "dn_detail", "warehouse"],
			limit_page_length=0,
		):
			source[r.name] = r

	mapping, unresolved, notes = {}, [], set()
	for row in rows:
		origin = source.get(cstr(row.get("sales_invoice_item")))
		if not origin or not origin.get("delivery_note") or not origin.get("dn_detail"):
			unresolved.append(cint(row.idx))
			continue
		mapping[row.name] = (origin["dn_detail"], row.get("warehouse") or origin.get("warehouse"))
		notes.add(origin["delivery_note"])

	return notes, mapping, unresolved


def _already_returned(dn_rows):
	"""``{delivery row: qty already returned}`` — as a positive number.

	ERPNext stores a return row's qty as NEGATIVE, so the sum is negated to read as
	"this much has come back". One query for the whole document.
	"""
	if not dn_rows:
		return {}
	rows = frappe.get_all(
		"Delivery Note Item",
		filters={"dn_detail": ("in", list(dn_rows)), "docstatus": 1},
		fields=["dn_detail", "sum(qty) as qty"],
		group_by="dn_detail",
	)
	return {r.dn_detail: -flt(r.qty) for r in rows}


def _exhausted(mapping):
	"""Rows whose delivered quantity has already been returned in full.

	Without this the button is offered, the operator fills nothing in, saves, and
	meets ERPNext's own `StockOverReturnError: Cannot return more than 0.0` — which is
	the guard working correctly but is a poor way to find out. Measured on yht-test:
	2 of the first 6 candidates were already fully returned.
	"""
	dn_rows = [dn_row for dn_row, _wh in mapping.values()]
	if not dn_rows:
		return []
	delivered = {
		r.name: flt(r.qty)
		for r in frappe.get_all(
			"Delivery Note Item", filters={"name": ("in", dn_rows)}, fields=["name", "qty"]
		)
	}
	returned = _already_returned(dn_rows)
	spent = []
	for credit_row, (dn_row, _wh) in mapping.items():
		remaining = flt(delivered.get(dn_row, 0)) - flt(returned.get(dn_row, 0))
		if remaining <= 0:
			spent.append(credit_row)
	return spent


@frappe.whitelist()
def can_make_delivery_note(source_name: str):
	"""What the form needs to decide whether to offer the button — and say why not."""
	if not allow_delivery_note_from_sales_return():
		return {"allowed": False, "reason": "disabled"}

	doc = frappe.get_doc("Sales Invoice", source_name)
	if not cint(doc.is_return) or doc.docstatus != 1:
		return {"allowed": False, "reason": "not a submitted sales return"}

	notes, mapping, unresolved = _resolve_rows(doc)
	existing = frappe.get_all(
		"Delivery Note Item",
		filters={"against_sales_invoice": source_name, "docstatus": ("<", 2)},
		pluck="parent",
		limit_page_length=1,
	)
	spent = _exhausted(mapping) if mapping else []
	return {
		"allowed": bool(mapping)
		and not unresolved
		and len(notes) == 1
		and not existing
		and not spent,
		"reason": (
			"already created" if existing
			else "no row links back to a delivery note" if not mapping
			else "rows %s do not link back to a delivery note" % ", ".join(str(i) for i in unresolved)
			if unresolved
			else "rows span %s delivery notes" % len(notes) if len(notes) != 1
			else "the delivered quantity has already been returned in full" if spent
			else ""
		),
		"delivery_note": list(notes)[0] if len(notes) == 1 else None,
		"existing": existing[0] if existing else None,
	}


@frappe.whitelist()
def make_delivery_note_from_sales_return(source_name: str, target_doc=None):
	"""Build the delivery return that brings the credited stock back."""
	if not allow_delivery_note_from_sales_return():
		frappe.throw(
			_("Creating a delivery return from a credit note is switched off. Turn it on in {0}.").format(
				"<b>YHT Return Settings</b>"
			),
			title=_("Not Enabled"),
		)

	credit_note = frappe.get_doc("Sales Invoice", source_name)
	if not cint(credit_note.is_return):
		frappe.throw(_("{0} is not a sales return.").format(source_name))
	if credit_note.docstatus != 1:
		frappe.throw(_("{0} has to be submitted first.").format(source_name))

	if not frappe.has_permission("Delivery Note", "create"):
		raise frappe.PermissionError(_("Not permitted to create a Delivery Note"))

	notes, mapping, unresolved = _resolve_rows(credit_note)
	if unresolved:
		frappe.throw(
			_(
				"Row {0}: this line does not trace back to a delivery note, so there is no "
				"delivered quantity to return against. A delivery return is only possible for "
				"goods that went out on a Delivery Note."
			).format(", ".join(str(i) for i in unresolved)),
			title=_("Nothing to Return"),
		)
	if not mapping:
		frappe.throw(
			_("None of these lines were delivered on a Delivery Note."), title=_("Nothing to Return")
		)
	if len(notes) != 1:
		# One delivery return can only reverse one delivery note: `return_against` is a
		# single link, and ERPNext counts the over-return against it.
		frappe.throw(
			_(
				"These lines came from {0} different delivery notes. Raise one delivery "
				"return per delivery note instead."
			).format(len(notes)),
			title=_("More Than One Delivery Note"),
		)

	original_note = list(notes)[0]

	spent = _exhausted(mapping)
	if spent:
		idx = sorted(
			cint(row.idx) for row in credit_note.get("items") or [] if row.name in spent
		)
		frappe.throw(
			_(
				"Row {0}: the delivered quantity has already been returned in full, so there "
				"is nothing left to bring back. Check the delivery note's own returns before "
				"raising another."
			).format(", ".join(str(i) for i in idx)),
			title=_("Already Returned"),
		)

	already = frappe.get_all(
		"Delivery Note Item",
		filters={"against_sales_invoice": source_name, "docstatus": ("<", 2)},
		pluck="parent",
		limit_page_length=1,
	)
	if already:
		frappe.throw(
			_("Delivery return {0} was already raised from this credit note.").format(already[0]),
			title=_("Already Created"),
		)

	def postprocess(source, target):
		target.is_return = 1
		target.return_against = original_note
		# The credit note already exists; asking for another one here would raise a
		# second reversal of the same invoice.
		if target.meta.has_field("issue_credit_note"):
			target.issue_credit_note = 0
		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

	def update_item(source_row, target_row, source_parent):
		dn_row, warehouse = mapping[source_row.name]
		# The credit note's quantities are already negative; copy them rather than
		# recomputing, so the two documents agree line for line.
		target_row.qty = flt(source_row.qty)
		target_row.stock_qty = flt(source_row.qty) * flt(source_row.conversion_factor or 1)
		# `dn_detail` is what ERPNext's over-return guard counts against — without it a
		# second delivery return of the same line saves with only a message.
		target_row.dn_detail = dn_row
		target_row.against_sales_invoice = source_parent.name
		target_row.si_detail = source_row.name
		if warehouse:
			target_row.warehouse = warehouse

	doc = get_mapped_doc(
		"Sales Invoice",
		source_name,
		{
			"Sales Invoice": {
				"doctype": "Delivery Note",
				"validation": {"docstatus": ["=", 1], "is_return": ["=", 1]},
			},
			"Sales Invoice Item": {
				"doctype": "Delivery Note Item",
				"field_map": {
					"serial_no": "serial_no",
					"batch_no": "batch_no",
					"cost_center": "cost_center",
					"sales_order": "against_sales_order",
					"so_detail": "so_detail",
				},
				"postprocess": update_item,
				"condition": lambda row: row.name in mapping,
			},
			"Sales Taxes and Charges": {"doctype": "Sales Taxes and Charges", "reset_value": True},
		},
		target_doc,
		postprocess,
	)
	return doc
