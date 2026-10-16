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
	table = _setup_connected_table()
	if skipped:
		frappe.log_error(message="\n".join(skipped), title="yht_custom: connected numbers")
	return {
		"created": {k: [f["fieldname"] for f in v] for k, v in to_create.items()},
		"placed": placed,
		"skipped": skipped,
		"table": table,
	}


def _setup_connected_table() -> dict:
	"""The right-hand "Connected Documents" table, the numbers hidden behind it, and tidier hints.

	The numbers stay as stored Data fields (list columns, filters, reports); on the form they are
	hidden (`depends_on` eval:0 — a hidden field would drop out of the list-view column picker) and one
	HTML field shows them as links. The two long hints under Fiscal Year and Other Remarks shrink so
	the first two columns stop crowding the third.
	"""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	from yht_custom.connected_documents import CUSTOM_FIELDS, TABLE_ANCHORS, TABLE_FIELD
	from yht_custom.meeting_1011 import _front_boundary, _live_order, place_after
	from yht_custom.other_remarks import DESCRIPTION as OTHER_REMARKS_HINT
	from yht_custom.setup import FISCAL_YEAR_HINT

	doctypes = [dt for dt in TABLE_ANCHORS if frappe.db.exists("DocType", dt)]
	create_custom_fields(
		{
			dt: [
				{
					"fieldname": TABLE_FIELD,
					"label": "Connected Documents",
					"fieldtype": "HTML",
					"insert_after": TABLE_ANCHORS[dt],
					"print_hide": 1,
				}
			]
			for dt in doctypes
			if not frappe.get_meta(dt).has_field(TABLE_FIELD)
		},
		ignore_validate=True,
	)
	placed, hidden, hints = [], [], []
	for dt in doctypes:
		frappe.clear_cache(doctype=dt)
		order = _live_order(dt)
		anchor = TABLE_ANCHORS[dt]
		if anchor in order and order.index(anchor) < _front_boundary(order) and place_after(dt, TABLE_FIELD, anchor):
			placed.append(dt)
		for name, _label in CUSTOM_FIELDS.get(dt, []):
			cf = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": name}, ["name", "depends_on"], as_dict=True)
			if cf and cf.depends_on != "eval:0":
				frappe.db.set_value("Custom Field", cf.name, {"depends_on": "eval:0", "description": ""})
				hidden.append(f"{dt}.{name}")
		for name, hint in (("custom_fiscal_year", FISCAL_YEAR_HINT), ("custom_other_remarks", OTHER_REMARKS_HINT)):
			cf = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": name}, ["name", "description"], as_dict=True)
			if cf and cf.description != hint:
				frappe.db.set_value("Custom Field", cf.name, "description", hint)
				hints.append(f"{dt}.{name}")
		frappe.clear_cache(doctype=dt)
	return {"placed": placed, "hidden": hidden, "hints": hints}
