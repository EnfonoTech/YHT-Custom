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

Extended on 2026-10-16 after the client's check ("this is for ALL invoice types, not just sales invoice and
delivery note; if any invoice is connected with any other it should reflect the number"): the same two
mechanisms now cover the whole chain, declared as data (`OWN_ROWS`, `BY_OTHERS`, `POINTS_AT`):

    Quotation         <- Sales Order No
    Sales Order       -> Quotation No;  <- Delivery Note No, Sales Invoice No
    Delivery Note     -> Sales Order No, Sales Invoice No          (dn_links)
    Sales Invoice     -> Sales Order No, Delivery Note No
    Purchase Order    <- Purchase Receipt No, Purchase Invoice No
    Purchase Receipt  -> Purchase Order No;  <- Purchase Invoice No
    Purchase Invoice  -> Purchase Order No, Purchase Receipt No

("->" is read from the document's own rows at validate; "<-" is refreshed from the other documents' rows
when they are submitted or cancelled.) Returns are never listed: a credit note already carries
`return_against` natively.

Behind `oct15_r46_connected_numbers`: the fields are created by the site's own provisioning, the
handlers do nothing until the switch is on, and nothing is ever written to a site that lacks a field.
"""

import frappe
from frappe.utils import cstr, flt

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
		# The right-hand table shows these as links; the data stays for list columns, filters, reports.
		"depends_on": "eval:0",
	}


#: 2026-10-16 — "show it as a table on the right side, click to open the document": one HTML field per
#: document, rendered by `public/js/connected_documents.js` from the stored numbers. Placed at the end of
#: the front page's third column (Delivery Note keeps its two approved fields, row 23, as they are).
TABLE_FIELD = "custom_connected_documents"
TABLE_ANCHORS = {
	"Quotation": "custom_print_with_arabic",
	"Sales Order": "skip_delivery_note",
	"Sales Invoice": "amended_from",
	"Purchase Order": "amended_from",
	"Purchase Receipt": "return_against",
	"Purchase Invoice": "amended_from",
}


#: doctype -> its fields, in front-page order.
CUSTOM_FIELDS = {
	"Quotation": [
		("custom_sales_order_no", "Sales Order No"),
	],
	"Sales Order": [
		("custom_quotation_no", "Quotation No"),
		("custom_delivery_note_no", "Delivery Note No"),
		("custom_sales_invoice_no", "Sales Invoice No"),
	],
	"Sales Invoice": [
		("custom_delivery_note_no", "Delivery Note No"),
		("custom_sales_order_no", "Sales Order No"),
	],
	"Purchase Order": [
		("custom_purchase_receipt_no", "Purchase Receipt No"),
		("custom_purchase_invoice_no", "Purchase Invoice No"),
	],
	"Purchase Receipt": [
		("custom_purchase_order_no", "Purchase Order No"),
		("custom_purchase_invoice_no", "Purchase Invoice No"),
	],
	"Purchase Invoice": [
		("custom_purchase_order_no", "Purchase Order No"),
		("custom_purchase_receipt_no", "Purchase Receipt No"),
	],
}

#: Read from the document's OWN item rows at `validate`: fieldname -> the row field holding the other
#: document's number. (Sales Invoice has its own handler, `set_invoice_numbers`: it also looks for notes
#: raised later.)
OWN_ROWS = {
	"Sales Order": {"custom_quotation_no": "prevdoc_docname"},
	"Purchase Receipt": {"custom_purchase_order_no": "purchase_order"},
	"Purchase Invoice": {"custom_purchase_order_no": "purchase_order", "custom_purchase_receipt_no": "purchase_receipt"},
}

#: Refreshed from OTHER documents' rows that name this one: fieldname -> (other doctype, its item
#: doctype, the item field holding this document's number).
BY_OTHERS = {
	"Quotation": {"custom_sales_order_no": ("Sales Order", "Sales Order Item", "prevdoc_docname")},
	"Purchase Order": {
		"custom_purchase_receipt_no": ("Purchase Receipt", "Purchase Receipt Item", "purchase_order"),
		"custom_purchase_invoice_no": ("Purchase Invoice", "Purchase Invoice Item", "purchase_order"),
	},
	"Purchase Receipt": {
		"custom_purchase_invoice_no": ("Purchase Invoice", "Purchase Invoice Item", "purchase_receipt"),
	},
}

#: When a document of this type is submitted or cancelled, these documents are refreshed:
#: doctype -> [(its item field naming the other document, the other doctype)].
POINTS_AT = {
	"Sales Order": [("prevdoc_docname", "Quotation")],
	"Purchase Receipt": [("purchase_order", "Purchase Order")],
	"Purchase Invoice": [("purchase_order", "Purchase Order"), ("purchase_receipt", "Purchase Receipt")],
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


# ------------------------------------------------------- the rest of the chain (2026-10-16)


def _check(*names):
	"""Table and column names cannot be bound as parameters; they come only from the maps above."""
	known_docs = {d for _f, d in sum(POINTS_AT.values(), [])} | set(POINTS_AT) | set(BY_OTHERS) | set(OWN_ROWS)
	known_children = {c for spec in BY_OTHERS.values() for (_d, c, _f) in spec.values()}
	known_fields = {f for spec in BY_OTHERS.values() for (_d, _c, f) in spec.values()} | {
		f for spec in OWN_ROWS.values() for f in spec.values()
	}
	for name in names:
		assert name in known_docs | known_children | known_fields, f"{name} is not in the connected-documents maps"


def _names_pointing_at(other_doctype, child_doctype, row_field, name):
	"""Submitted, non-return documents of `other_doctype` whose item rows name `name`."""
	_check(other_doctype, child_doctype, row_field)
	returns = " AND d.is_return = 0" if frappe.get_meta(other_doctype).has_field("is_return") else ""
	return frappe.db.sql(
		f"""SELECT DISTINCT d.name FROM `tab{other_doctype}` d
		INNER JOIN `tab{child_doctype}` i ON i.parent = d.name
		WHERE i.`{row_field}` = %s AND d.docstatus = 1{returns}
		ORDER BY d.creation""",
		(name,),
		pluck=True,
	)


def refresh_by_others(doctype, name) -> bool:
	"""The fields of `doctype` that are read from other documents' rows."""
	spec = BY_OTHERS.get(doctype)
	if not spec or not name or not frappe.db.exists(doctype, name):
		return False
	values = {
		fieldname: _joined(_names_pointing_at(other, child, row_field, name))
		for fieldname, (other, child, row_field) in spec.items()
	}
	return _write(doctype, name, values)


def _own_values(doctype, name):
	"""The OWN-row fields of a stored document, read from its saved rows."""
	meta = frappe.get_meta(doctype)
	child = meta.get_field("items").options
	values = {}
	for fieldname, row_field in OWN_ROWS.get(doctype, {}).items():
		_check(row_field)
		values[fieldname] = _joined(
			frappe.db.sql(
				f"SELECT `{row_field}` FROM `tab{child}` WHERE parent = %s AND IFNULL(`{row_field}`, '') != '' ORDER BY idx",
				(name,),
				pluck=True,
			)
		)
	return values


def refresh_own(doctype, name) -> bool:
	if doctype not in OWN_ROWS or not frappe.db.exists(doctype, name):
		return False
	return _write(doctype, name, _own_values(doctype, name))


def set_own_numbers(doc, method=None):
	"""`validate` on Sales Order, Purchase Receipt and Purchase Invoice — what the rows already say."""
	if not features.enabled(FEATURE):
		return
	for fieldname, row_field in OWN_ROWS.get(doc.doctype, {}).items():
		if doc.meta.has_field(fieldname):
			doc.set(fieldname, _joined(r.get(row_field) for r in doc.get("items") or []))


def after_document(doc, method=None):
	"""`on_submit` / `on_cancel` — the documents this one points at count their connections again."""
	if not features.enabled(FEATURE):
		return
	for row_field, target in POINTS_AT.get(doc.doctype, []):
		for name in {cstr(r.get(row_field)).strip() for r in doc.get("items") or []} - {""}:
			refresh_by_others(target, name)


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


# ------------------------------------------------------------- payments


#: The documents a Payment Entry is made AGAINST (its reference rows name them).
PAYMENT_AGAINST = ("Sales Invoice", "Sales Order", "Purchase Invoice", "Purchase Order")


@frappe.whitelist()
def linked_payments(doctype: str, name: str) -> list:
	"""The submitted Payment Entries paid against one document, for the Connected Documents table.

	Read live, not stored: a payment is made and cancelled all day and the Payment Entry's own submit and
	cancel would otherwise have to refresh this document too. Returns [] for a document or a Payment Entry
	the caller may not read — never a name the caller could not open. One row per Payment Entry, with the
	amount allocated TO THIS DOCUMENT (a receipt can settle several invoices).
	"""
	if doctype not in PAYMENT_AGAINST or not name:
		return []
	if not frappe.has_permission(doctype, "read", doc=name) or not frappe.has_permission("Payment Entry", "read"):
		return []

	allocated = {}
	for row in frappe.get_all(
		"Payment Entry Reference",
		filters={"parenttype": "Payment Entry", "reference_doctype": doctype, "reference_name": name},
		fields=["parent", "allocated_amount"],
		limit_page_length=0,
	):
		allocated[row.parent] = flt(allocated.get(row.parent)) + flt(row.allocated_amount)
	if not allocated:
		return []

	currency = frappe.db.get_value(doctype, name, "currency")
	entries = frappe.get_list(
		"Payment Entry",
		filters={"name": ["in", list(allocated)], "docstatus": 1},
		fields=["name", "posting_date", "payment_type"],
		order_by="posting_date asc, creation asc",
		limit_page_length=50,
	)
	return [
		{
			"name": e.name,
			"posting_date": cstr(e.posting_date),
			"payment_type": e.payment_type,
			"allocated_amount": allocated[e.name],
			"currency": currency,
		}
		for e in entries
	]


# ----------------------------------------------------------------- backfill


def backfill(commit: bool = False) -> dict:
	"""Fill the fields on every existing submitted document of the chain.

	    bench --site … execute yht_custom.connected_documents.backfill --kwargs "{'commit': True}"
	"""
	invoices = frappe.get_all("Sales Invoice", filters={"docstatus": 1, "is_return": 0}, pluck="name", limit=0)
	orders = frappe.get_all("Sales Order", filters={"docstatus": 1}, pluck="name", limit=0)
	changed = {"Sales Order": 0, "Sales Invoice": 0}
	extra = {}
	for doctype in set(OWN_ROWS) | set(BY_OTHERS):
		if doctype in ("Sales Order",):
			continue
		extra[doctype] = frappe.get_all(doctype, filters={"docstatus": 1}, pluck="name", limit=0)
		changed[doctype] = 0
	if commit:
		for name in orders:
			changed["Sales Order"] += int(refresh_order(name)) + int(refresh_own("Sales Order", name))
		for name in invoices:
			changed["Sales Invoice"] += int(refresh_invoice(name))
		for doctype, names in extra.items():
			for name in names:
				changed[doctype] += int(refresh_own(doctype, name)) + int(refresh_by_others(doctype, name))
		frappe.db.commit()
	summary = {
		"committed": bool(commit),
		"orders": len(orders),
		"invoices": len(invoices),
		**{doctype.lower().replace(" ", "_") + "s": len(names) for doctype, names in extra.items()},
		"updated": changed,
	}
	print(frappe.as_json(summary, indent=1))
	return summary
