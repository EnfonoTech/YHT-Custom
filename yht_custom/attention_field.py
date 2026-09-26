# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""The `Attention` line on customer-facing documents (meeting 2026-09-23, CR-011).

The client's ask, in his own words: *"just a text field is enough there... a
company has many purchase staff"* — a free-text note naming the person at the
customer the document is addressed to, printed on the document.

**A plain Data field, deliberately — not a Link to Contact.** A Link would look
tidier and is the wrong answer here: the whole point is the person is often NOT a
Contact record (a name heard on the phone, a buyer at the customer's site), and a
Link would force the operator to create a Contact before they can type a name.
The client asked for text; text is also the honest model.

Scope is the four SELLING documents. The meeting transcript says
*"Quotation / SO / SI / Purchase docs (scope TBC)"*, and the buying side is left
out on purpose: nobody named a buying use case, and a field nobody fills is worse
than no field. Adding Purchase Order/Invoice later is one line each.
"""

import frappe

DOCTYPES = ("Quotation", "Sales Order", "Sales Invoice", "Delivery Note")

FIELDNAME = "custom_attention"
LABEL = "Attention"

#: Where the field should sit, most-preferred first. Resolved against live meta
#: rather than hardcoded: `contact_person` is the natural neighbour but is not
#: guaranteed to be present or visible on every one of the four.
ANCHORS = ("contact_person", "contact_display", "customer_name", "party_name", "customer")


def _resolve_anchor(meta) -> str | None:
	for candidate in ANCHORS:
		if meta.get_field(candidate):
			return candidate
	return None


def ensure_attention_field() -> dict[str, str]:
	"""Create the Attention field on each selling doctype. Idempotent.

	Its own `PROVISIONING_STEPS` entry so one doctype's missing anchor is reported
	as itself rather than hidden behind another item's exception.
	"""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	fields, placed = {}, {}
	for doctype in DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		anchor = _resolve_anchor(frappe.get_meta(doctype))
		if not anchor:
			frappe.log_error(
				message=f"{doctype}: none of {ANCHORS} exists; Attention field not added",
				title="YHT attention field",
			)
			continue
		fields[doctype] = [
			{
				"fieldname": FIELDNAME,
				"label": LABEL,
				"fieldtype": "Data",
				"insert_after": anchor,
				"allow_on_submit": 1,
				"translatable": 0,
				"description": "Person at the customer this document is addressed to.",
			}
		]
		placed[doctype] = anchor

	if fields:
		create_custom_fields(fields, ignore_validate=True)

	return placed
