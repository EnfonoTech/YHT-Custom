# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Row 46 (meeting 2026-10-15) — the numbers of connected documents, on the front page.

Client, in the meeting: "if this invoice is connected to a delivery note or a sales order, it
should just pop up over here with the number, same as the old system". CR-008 (`dn_links`) already
does this for the Delivery Note; this extends it to the other two sides of the sales chain:

    Sales Invoice  ->  Delivery Note No, Sales Order No
    Sales Order    ->  Delivery Note No, Sales Invoice No
    Delivery Note  ->  Sales Order No, Sales Invoice No        (dn_links, unchanged)

Same design reasons as `dn_links`: stored Data fields rather than a computed block, so a list view,
a report column, a filter and a print format can all read them; written with `frappe.db.set_value`
and `update_modified=False` on submitted documents, so linking a document does not make every open
copy of its neighbour stale, and never through `save()`.

Where each number is knowable:

* a Sales Invoice knows its own orders and (DN-first) notes from its rows at `validate`; the notes
  of an invoice raised FIRST are only created later, so the Delivery Note's own submit/cancel
  refreshes the invoice (`against_sales_invoice` on the note's rows);
* a Sales Order has neither: both lists come from the other documents' rows, so a Delivery Note
  or a Sales Invoice submit/cancel refreshes it. A cancelled document drops off because only
  SUBMITTED, non-return documents are counted, and both events re-ask the same question.

Behind `oct15_r46_connected_numbers`: the fields are created by the site's own provisioning, the
handlers do nothing until the switch is on, and nothing is ever written to a site that lacks a field.
"""

import frappe
from frappe.utils import cstr

from yht_custom import features
from yht_custom.dn_links import _joined

FEATURE = "oct15_r46_connected_numbers"


def _field(fieldname, label, insert_after):
	return {
		"fieldname": fieldname,
		"label": label,
		"fieldtype": "Data",
		"insert_after": insert_after,
		"read_only": 1,
		"allow_on_submit": 1,
		"no_copy": 1,
		"print_hide": 1,
		"description": "Filled in automatically from the connected documents.",
	}


#: doctype -> its two fields, in front-page order.
CUSTOM_FIELDS = {
	"Sales Invoice": [
		("custom_delivery_note_no", "Delivery Note No"),
		("custom_sales_order_no", "Sales Order No"),
	],
	"Sales Order": [
		("custom_delivery_note_no", "Delivery Note No"),
		("custom_sales_invoice_no", "Sales Invoice No"),
	],
}


def _notes_of_order(order):
	return frappe.db.sql(
		"""SELECT DISTINCT dn.name FROM `tabDelivery Note` dn
		INNER JOIN `tabDelivery Note Item` i ON i.parent = dn.name
		WHERE i.against_sales_order = %s AND dn.docstatus = 1 AND dn.is_return = 0
		ORDER BY dn.posting_date, dn.creation""",
		(order,),
		pluck=True,
	)


def _invoices_of_order(order):
	return frappe.db.sql(
		"""SELECT DISTINCT si.name FROM `tabSales Invoice` si
		INNER JOIN `tabSales Invoice Item` i ON i.parent = si.name
		WHERE i.sales_order = %s AND si.docstatus = 1 AND si.is_return = 0
		ORDER BY si.posting_date, si.creation""",
		(order,),
		pluck=True,
	)


def _notes_of_invoice(invoice):
	"""Notes that name this invoice, from either direction (DN-first rows, SI-first rows)."""
	own = frappe.db.sql(
		"""SELECT DISTINCT i.delivery_note FROM `tabSales Invoice Item` i
		WHERE i.parent = %s AND IFNULL(i.delivery_note, '') != '' ORDER BY i.idx""",
		(invoice,),
		pluck=True,
	)
	later = frappe.db.sql(
		"""SELECT DISTINCT dn.name FROM `tabDelivery Note` dn
		INNER JOIN `tabDelivery Note Item` i ON i.parent = dn.name
		WHERE i.against_sales_invoice = %s AND dn.docstatus = 1 AND dn.is_return = 0
		ORDER BY dn.posting_date, dn.creation""",
		(invoice,),
		pluck=True,
	)
	return list(own) + list(later)


def _write(doctype, name, values):
	meta = frappe.get_meta(doctype)
	values = {k: v for k, v in values.items() if meta.has_field(k)}
	if not values:
		return False
	current = frappe.db.get_value(doctype, name, list(values), as_dict=True)
	if not current:
		return False
	changed = {k: v for k, v in values.items() if cstr(current.get(k)) != v}
	if changed:
		frappe.db.set_value(doctype, name, changed, update_modified=False)
	return bool(changed)


def refresh_order(order) -> bool:
	if not order or not frappe.db.exists("Sales Order", order):
		return False
	return _write(
		"Sales Order",
		order,
		{
			"custom_delivery_note_no": _joined(_notes_of_order(order)),
			"custom_sales_invoice_no": _joined(_invoices_of_order(order)),
		},
	)


def refresh_invoice(invoice) -> bool:
	if not invoice or not frappe.db.exists("Sales Invoice", invoice):
		return False
	orders = frappe.db.sql(
		"SELECT DISTINCT sales_order FROM `tabSales Invoice Item` WHERE parent = %s AND IFNULL(sales_order, '') != '' ORDER BY idx",
		(invoice,),
		pluck=True,
	)
	return _write(
		"Sales Invoice",
		invoice,
		{
			"custom_delivery_note_no": _joined(_notes_of_invoice(invoice)),
			"custom_sales_order_no": _joined(orders),
		},
	)


# ------------------------------------------------------------------- handlers


def set_invoice_numbers(doc, method=None):
	"""`Sales Invoice.validate` — what the invoice's own rows already say."""
	if not features.enabled(FEATURE):
		return
	if doc.meta.has_field("custom_sales_order_no"):
		doc.custom_sales_order_no = _joined(r.get("sales_order") for r in doc.get("items") or [])
	if doc.meta.has_field("custom_delivery_note_no"):
		own = [r.get("delivery_note") for r in doc.get("items") or []]
		later = [] if doc.is_new() else _notes_of_invoice(doc.name)
		doc.custom_delivery_note_no = _joined(own + later)


def after_invoice(doc, method=None):
	"""`Sales Invoice.on_submit` / `on_cancel` — the orders it touches count their invoices again."""
	if not features.enabled(FEATURE):
		return
	for order in {cstr(r.get("sales_order")).strip() for r in doc.get("items") or []} - {""}:
		refresh_order(order)


def after_note(doc, method=None):
	"""`Delivery Note.on_submit` / `on_cancel` — the orders and invoices it touches count their notes again."""
	if not features.enabled(FEATURE):
		return
	rows = doc.get("items") or []
	for order in {cstr(r.get("against_sales_order")).strip() for r in rows} - {""}:
		refresh_order(order)
	for invoice in {cstr(r.get("against_sales_invoice")).strip() for r in rows} - {""}:
		refresh_invoice(invoice)


# ------------------------------------------------------- Quotation sales team


def fill_quotation_sales_team(doc, method=None):
	"""`Quotation.before_validate` — the customer's team, when the document has none yet (row 42).

	ERPNext fills a team from the customer itself (`get_party_details`) on every selling document
	that HAS the table; Quotation upstream does not, so `selling_controller` drops it
	(`party_details.pop("sales_team")`). With the table added, the form and server fill it the usual
	way; this covers a quotation made by a mapper (Opportunity -> Quotation) or an import, which
	never calls party details. An existing team is never touched.
	"""
	if not features.enabled("oct15_r42_quotation_sales_team"):
		return
	if not doc.meta.has_field("sales_team") or doc.get("sales_team"):
		return
	if cstr(doc.get("quotation_to")) != "Customer" or not doc.get("party_name"):
		return
	for row in frappe.get_all(
		"Sales Team",
		filters={"parenttype": "Customer", "parent": doc.party_name},
		fields=["sales_person", "allocated_percentage", "commission_rate"],
		order_by="idx asc",
	):
		doc.append("sales_team", row)


# ----------------------------------------------------------------- backfill


def backfill(commit: bool = False) -> dict:
	"""Fill the fields on every existing submitted Sales Order and Sales Invoice.

	    bench --site … execute yht_custom.connected_documents.backfill --kwargs "{'commit': True}"
	"""
	orders = frappe.get_all("Sales Order", filters={"docstatus": 1}, pluck="name", limit=0)
	invoices = frappe.get_all("Sales Invoice", filters={"docstatus": 1, "is_return": 0}, pluck="name", limit=0)
	changed = {"Sales Order": 0, "Sales Invoice": 0}
	if commit:
		for name in orders:
			changed["Sales Order"] += int(refresh_order(name))
		for name in invoices:
			changed["Sales Invoice"] += int(refresh_invoice(name))
		frappe.db.commit()
	summary = {"committed": bool(commit), "orders": len(orders), "invoices": len(invoices), "updated": changed}
	print(frappe.as_json(summary, indent=1))
	return summary
