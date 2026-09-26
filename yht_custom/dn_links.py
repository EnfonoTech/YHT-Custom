# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""CR-008 — the Sales Order and Sales Invoice numbers, on the Delivery Note's front page.

Client's words: "the connected document… instead of clicking on each tab, keep
that number there itself". Today both live in the Connections tab, which is three
clicks and a page the driver's copy never shows.

## Why these are stored fields and not a computed HTML block

Because the client asked to SEE them, and on this site "see" has never meant only
"on the form": `form_layout` puts columns in list views, the two custom reports
are Report Builder reports, and a Data field is the only shape that a list view, a
report column, a filter and a print format can all read. A computed block would
answer the form and nothing else.

## Where each number comes from, and why they are not symmetric

`against_sales_order` is written by ERPNext onto the note's own item rows at
creation, in every flow, so the Sales Order number is knowable when the note is
saved and is derived on `validate`.

The invoice number is NOT. The ordinary flow here is note first, invoice later —
1,872 of 1,964 notes — and `against_sales_invoice` is only filled in the
SI-first direction. What links the two in the DN-first flow is
`Sales Invoice Item.delivery_note`, which is written when the INVOICE is saved,
long after the note. So the invoice number is refreshed from the invoice's own
submit and cancel, by `frappe.db.set_value` on the note.

🔴 WRITTEN WITH `frappe.db.set_value`, AND `update_modified=False`. A direct
UPDATE never consults `allow_on_submit`, and leaving `modified` alone means
invoicing a note does not make every open copy of it stale.

⚠️ AND THESE TWO **DO** CARRY `allow_on_submit`, WHICH IS THE OPPOSITE OF WHAT
`delivery_backlink` CHOSE FOR ITS LINK FIELDS — the difference is deliberate and
is about what depends on the value. `dn_detail` / `delivery_note` drive ERPNext's
own over-return guard and `update_billing_status`, so a stale form silently
writing an old value there is corruption and a loud `UpdateAfterSubmitError` is
the better outcome. These two drive NOTHING: they are a mirror of the Connections
tab, for reading. With `allow_on_submit = 0` every ordinary after-submit edit —
Other Remarks, say — on a note whose invoice was raised while the form was open
would be refused with an error about a field the operator cannot even edit. The
worst case here is a number that reads stale until the next invoice event
rewrites it, which is strictly better than blocking the edit.

⚠️ A CANCELLED INVOICE DROPS OFF THE NOTE. `_invoices_for` counts submitted
invoices only and both events re-ask the same question, so cancel is not a
separate code path — the same idempotent rule that makes `delivery_backlink`
correct at both ends.
"""

import frappe
from frappe.utils import cstr

FIELDS = ("custom_sales_order_no", "custom_sales_invoice_no")

CUSTOM_FIELDS = [
	{
		"fieldname": "custom_sales_order_no",
		"label": "Sales Order No",
		"fieldtype": "Data",
		"insert_after": "po_date",
		"read_only": 1,
		"allow_on_submit": 1,
		"description": "Derived from the item rows. More than one order shows as a comma-separated list.",
	},
	{
		"fieldname": "custom_sales_invoice_no",
		"label": "Sales Invoice No",
		"fieldtype": "Data",
		"insert_after": "custom_sales_order_no",
		"read_only": 1,
		"allow_on_submit": 1,
		"description": "Filled when the invoice is submitted; cleared if it is cancelled.",
	},
]


def _joined(values) -> str:
	"""Distinct, order-preserving, comma-joined — and never longer than the column.

	A note split across four orders is ordinary here. `Data` is 140 characters, and
	a value that overflows raises `DataError (1406)` on save, which would make the
	note unsaveable for a display field. Truncation with a trailing `…` is the
	honest failure: the field says there are more, and the Connections tab remains
	the complete answer.
	"""
	seen, out = set(), []
	for value in values:
		value = cstr(value).strip()
		if value and value not in seen:
			seen.add(value)
			out.append(value)
	joined = ", ".join(out)
	return joined if len(joined) <= 140 else joined[:137].rstrip(", ") + "…"


def _orders_for(doc) -> str:
	return _joined(row.get("against_sales_order") for row in doc.get("items") or [])


def _invoices_for(note: str) -> str:
	"""Submitted invoices that name this note, from EITHER direction.

	One query per direction, both indexed on the column they filter. `delivery_note`
	is the DN-first link ERPNext writes on the invoice; `against_sales_invoice` on
	the note's own rows is the SI-first one.
	"""
	rows = frappe.get_all(
		"Sales Invoice Item",
		filters={"delivery_note": note, "docstatus": 1},
		fields=["parent"],
		order_by="parent asc",
	)
	from_note = frappe.get_all(
		"Delivery Note Item",
		filters={"parent": note, "against_sales_invoice": ["is", "set"]},
		pluck="against_sales_invoice",
		order_by="idx asc",
	)
	submitted = [
		name
		for name in from_note
		if frappe.db.get_value("Sales Invoice", name, "docstatus") == 1
	]
	return _joined([row.parent for row in rows] + submitted)


# ------------------------------------------------------------------- handlers


def set_order_numbers(doc, method=None):
	"""`Delivery Note.validate` — the order number, which is knowable now."""
	if not doc.meta.has_field("custom_sales_order_no"):
		return
	doc.custom_sales_order_no = _orders_for(doc)


def refresh_from_invoice(doc, method=None):
	"""`Sales Invoice.on_submit` / `on_cancel` — re-ask for every note it touches."""
	if not frappe.get_meta("Delivery Note").has_field("custom_sales_invoice_no"):
		return

	notes = {cstr(row.get("delivery_note")).strip() for row in doc.get("items") or []}
	notes.discard("")
	for note in sorted(notes):
		if not frappe.db.exists("Delivery Note", note):
			continue
		value = _invoices_for(note)
		if cstr(frappe.db.get_value("Delivery Note", note, "custom_sales_invoice_no")) != value:
			frappe.db.set_value(
				"Delivery Note", note, "custom_sales_invoice_no", value, update_modified=False
			)


# --------------------------------------------------------------------- setup


def setup_delivery_note_links() -> dict:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields({"Delivery Note": CUSTOM_FIELDS}, ignore_validate=True)
	return {"fields": list(FIELDS)}


def backfill(commit: bool = False) -> dict:
	"""Fill both fields on every existing note.

	    bench --site … execute yht_custom.dn_links.backfill --kwargs "{'commit': True}"
	"""
	notes = frappe.get_all("Delivery Note", pluck="name", limit=0)
	written = 0

	for note in notes:
		orders = _joined(
			frappe.get_all(
				"Delivery Note Item", filters={"parent": note}, pluck="against_sales_order", order_by="idx asc"
			)
		)
		invoices = _invoices_for(note)
		current = frappe.db.get_value(
			"Delivery Note", note, ["custom_sales_order_no", "custom_sales_invoice_no"], as_dict=True
		)
		if cstr(current.custom_sales_order_no) == orders and cstr(current.custom_sales_invoice_no) == invoices:
			continue
		if commit:
			frappe.db.set_value(
				"Delivery Note",
				note,
				{"custom_sales_order_no": orders, "custom_sales_invoice_no": invoices},
				update_modified=False,
			)
		written += 1

	if commit:
		frappe.db.commit()

	summary = {"committed": bool(commit), "notes": len(notes), "updated": written}
	print(frappe.as_json(summary, indent=1))
	return summary
