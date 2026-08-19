# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Form trimming for the branch document set.

The client's brief (MoM §2.5) is "reduced screens": a branch operator raising an
invoice should not be looking at fields this business never uses.

Applied as **Property Setters**, not client-side JS, because:

* a hidden-by-JS field still renders for a moment and still tab-focuses
* Property Setters survive without an asset build
* these are business-wide facts, not per-role preferences — YHT trades in SAR
  only and does not use Projects, so the fields are noise for accountants too

Anything genuinely role-dependent (the cost centre, `update_stock`) stays in
`branch_user_forms.js` / `sales_flow.js` where it can read `frappe.user_roles`.
"""

import json

import frappe

#: Fields hidden across the transacting set.
#:
#: `project` — YHT does not run project accounting; the Accounting Dimensions
#: section asks for it on every document.
#: `currency` / `conversion_rate` — the company trades in SAR only. The value is
#: still set and still posts; only the input is hidden.
HIDE_FIELDS = {
	# `time_sheet_list` is ERPNext's project time-billing block — a Time Sheets
	# grid with Activity Type / Billing Hours / Billing Amount. YHT is a trading
	# business and bills goods, never hours, so it is pure noise on every invoice.
	# Hiding the SECTION collapses the whole block; the three fields inside are
	# listed too so they cannot surface via a search or a print format.
	"Sales Invoice": [
		"project",
		"currency",
		"conversion_rate",
		"time_sheet_list",
		"timesheets",
		"total_billing_hours",
		"total_billing_amount",
	],
	"Sales Order": ["project", "currency", "conversion_rate"],
	"Delivery Note": ["project", "currency", "conversion_rate"],
	"Quotation": ["project", "currency", "conversion_rate"],
	"Purchase Invoice": ["project", "currency", "conversion_rate"],
	"Purchase Receipt": ["project", "currency", "conversion_rate"],
	"Payment Entry": ["project"],
}

#: Move a field to sit immediately after an anchor: {doctype: [(field, anchor)]}
#:
#: The price list belongs next to the stock decision — the operator picking what
#: to charge is the same operator deciding whether this document moves stock.
MOVE_AFTER = {
	"Sales Invoice": [("selling_price_list", "update_stock")],
	"Delivery Note": [("selling_price_list", "set_warehouse")],
	"Purchase Invoice": [("buying_price_list", "update_stock")],
}


def setup_form_layout():
	"""Idempotent. Safe to re-run on every after_migrate."""
	_hide_fields()
	_reorder_fields()
	_default_branch_series()


def _hide_fields():
	for doctype, fieldnames in HIDE_FIELDS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		for fieldname in fieldnames:
			if not meta.get_field(fieldname):
				continue
			_set_property(doctype, fieldname, "hidden", "1", "Check")


def _reorder_fields():
	"""Rebuild the doctype's `field_order` with the field moved after its anchor.

	The Property Setter carries the **entire** field list, which is why the order
	is computed from live metadata rather than hardcoded: a hardcoded list would
	silently drop every field a later ERPNext version adds. Re-running
	`after_migrate` after an upgrade repairs the order for the new field set.
	"""
	for doctype, moves in MOVE_AFTER.items():
		if not frappe.db.exists("DocType", doctype):
			continue

		meta = frappe.get_meta(doctype)
		order = [df.fieldname for df in meta.fields if not getattr(df, "is_custom_field", False)]

		changed = False
		for fieldname, anchor in moves:
			if fieldname not in order or anchor not in order:
				continue
			if order.index(fieldname) == order.index(anchor) + 1:
				continue  # already in place
			order.remove(fieldname)
			order.insert(order.index(anchor) + 1, fieldname)
			changed = True

		if not changed:
			continue

		existing = frappe.db.get_value(
			"Property Setter",
			{"doc_type": doctype, "doctype_or_field": "DocType", "property": "field_order"},
			["name", "value"],
			as_dict=True,
		)
		value = json.dumps(order)
		if existing:
			if existing.value != value:
				frappe.db.set_value("Property Setter", existing.name, "value", value)
		else:
			frappe.make_property_setter(
				{
					"doctype": doctype,
					"doctype_or_field": "DocType",
					"property": "field_order",
					"value": value,
					"property_type": "Text",
				},
				validate_fields_for_doctype=False,
			)


def _default_branch_series():
	"""Show the branch series on a new form, not ERPNext's `ACC-SINV-` default.

	`branch_defaults.set_naming_series_from_branch` already overrides the series
	server-side at `before_insert`, so the saved name was always right — but the
	form displayed the first option in the list, so operators saw `ACC-SINV-.YYYY.-`
	and reasonably assumed the branch numbering was not working.
	"""
	branch = frappe.db.get_value("Branch Configuration", {}, "branch")
	prefix = (frappe.db.get_value("Branch", branch, "custom_doc_prefix") or "").strip() if branch else ""
	if not prefix:
		return

	for row in frappe.get_all(
		"Branch Naming Series",
		filters={"parent": branch, "use_for_return": 0},
		fields=["parent_doctype", "naming_series"],
	):
		doctype, series = row.parent_doctype, row.naming_series
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		field = meta.get_field("naming_series")
		if not field:
			continue
		# Only default to a series the picker actually offers, or Frappe rejects
		# the saved document.
		options = (field.options or "").split("\n")
		if series not in options:
			continue
		_set_property(doctype, "naming_series", "default", series, "Text")


def _set_property(doctype, fieldname, prop, value, property_type):
	existing = frappe.db.get_value(
		"Property Setter",
		{"doc_type": doctype, "field_name": fieldname, "property": prop},
		["name", "value"],
		as_dict=True,
	)
	if existing:
		if str(existing.value) != str(value):
			frappe.db.set_value("Property Setter", existing.name, "value", value)
		return
	frappe.make_property_setter(
		{
			"doctype": doctype,
			"fieldname": fieldname,
			"property": prop,
			"value": value,
			"property_type": property_type,
		},
		validate_fields_for_doctype=False,
	)
