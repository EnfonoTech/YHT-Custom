# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Meeting of 2026-10-15 — the provisioning for rows 42, 43 and 46.

Each step is idempotent, writes no commit, and sits behind its own `oct15_*` switch: the shared
bench serves the live site and UAT from one `apps/yht_custom`, so what a migrate would otherwise
carry to live is held back until the site asks (CLAUDE.md, gotcha 106).
"""

import frappe

from yht_custom import features

R42 = "oct15_r42_quotation_sales_team"
R43 = "oct15_r43_opportunity_bulk_items"
R46 = "oct15_r46_connected_numbers"


# --------------------------------------------------------------------- row 43


def setup_opportunity_bulk_items() -> dict:
	"""Row 43 — Download / Upload on the Opportunity's items grid, as on Quotation.

	`Quotation.items` carries `allow_bulk_edit = 1`, which is what makes the grid draw those two
	buttons; `Opportunity.items` ships with 0.
	"""
	if not features.enabled(R43):
		return {"skipped": f"{R43} is off for this site"}
	if not frappe.db.exists("DocType", "Opportunity"):
		return {}

	from yht_custom.form_layout import _set_property

	_set_property("Opportunity", "items", "allow_bulk_edit", "1", "Check")
	frappe.clear_cache(doctype="Opportunity")
	return {"Opportunity.items": "allow_bulk_edit = 1"}


# --------------------------------------------------------------------- row 42


def setup_quotation_sales_team() -> dict:
	"""Row 42 — a Sales Team table on Quotation.

	ERPNext does not ship one (Sales Order, Sales Invoice and Delivery Note have it), so the team
	never reached a quotation however the customer was set up. With the table present the standard
	party-details code fills it from the customer on the form and on the server, and
	`selling_controller` stops dropping it. Named `sales_team` like its siblings so everything that
	already reads that name — the row-30 front block, `print_helpers.yht_sales_person` — works unchanged.
	"""
	if not features.enabled(R42):
		return {"skipped": f"{R42} is off for this site"}
	if not frappe.db.exists("DocType", "Quotation"):
		return {}
	if frappe.get_meta("Quotation").has_field("sales_team"):
		return {"adopted": "Quotation.sales_team already exists"}

	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(
		{
			"Quotation": [
				{
					"fieldname": "sales_team",
					"label": "Sales Team",
					"fieldtype": "Table",
					"options": "Sales Team",
					"insert_after": "referral_sales_partner",
					"no_copy": 0,
					"print_hide": 1,
				}
			]
		},
		ignore_validate=True,
	)
	frappe.clear_cache(doctype="Quotation")
	return {"created": "Quotation.sales_team"}


# --------------------------------------------------------------------- row 46


#: Candidate anchors on the front page, in order, for the two connected-number fields.
CONNECTED_ANCHORS = {
	"Quotation": ("valid_till", "transaction_date", "party_name"),
	"Sales Invoice": ("po_date", "po_no", "company_tax_id", "company"),
	"Sales Order": ("po_date", "po_no", "customer_name", "customer"),
	"Purchase Order": ("schedule_date", "transaction_date", "supplier_name"),
	"Purchase Receipt": ("supplier_delivery_note", "posting_date", "supplier_name"),
	"Purchase Invoice": ("bill_date", "bill_no", "posting_date", "supplier_name"),
}


def setup_connected_numbers() -> dict:
	"""Row 46 — create the fields on Sales Invoice and Sales Order and bring them to the front page."""
	if not features.enabled(R46):
		return {"skipped": f"{R46} is off for this site"}

	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	from yht_custom.connected_documents import CUSTOM_FIELDS, _field
	from yht_custom.meeting_1011 import _front_boundary, _live_order, place_after

	to_create = {}
	for doctype, fields in CUSTOM_FIELDS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		missing = [(n, label) for n, label in fields if not meta.has_field(n)]
		if missing:
			to_create[doctype] = [_field(n, label, CONNECTED_ANCHORS[doctype][0]) for n, label in missing]
	if to_create:
		create_custom_fields(to_create, ignore_validate=True)

	placed, skipped = [], []
	for doctype, fields in CUSTOM_FIELDS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		frappe.clear_cache(doctype=doctype)
		order = _live_order(doctype)
		boundary = _front_boundary(order)
		anchor = next((a for a in CONNECTED_ANCHORS[doctype] if a in order and order.index(a) < boundary), None)
		if not anchor:
			skipped.append(f"{doctype}: no front-page anchor")
			continue
		previous = anchor
		for name, _label in fields:
			if name in order and place_after(doctype, name, previous):
				placed.append(f"{doctype}.{name}")
			previous = name
	if skipped:
		frappe.log_error(message="\n".join(skipped), title="yht_custom: connected numbers")
	return {"created": {k: [f["fieldname"] for f in v] for k, v in to_create.items()}, "placed": placed, "skipped": skipped}
