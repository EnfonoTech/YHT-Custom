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

#: The `Currency and Price List` accordion, emptied of anything YHT uses.
#:
#: MEASURED, not assumed — before this change the section still held
#: `price_list_currency`, `plc_conversion_rate` and `ignore_pricing_rule` on all
#: six doctypes, so it only LOOKED empty because it renders collapsed. It is
#: hidden here rather than left collapsed because:
#:
#: * 0 Price Lists on this site carry a non-SAR currency, so `price_list_currency`
#:   and `plc_conversion_rate` can only ever read SAR / 1.0
#: * 0 Pricing Rules exist, so `ignore_pricing_rule` overrides nothing
#:
#: Hiding a Section Break collapses everything inside it, but the inner fields are
#: listed too so they cannot resurface through a search, a report column or a
#: print format — same belt-and-braces as the Time Sheet block below.
_CURRENCY_SECTION = (
	"currency_and_price_list",
	"price_list_currency",
	"plc_conversion_rate",
	"ignore_pricing_rule",
)

#: Item 3 of the client sheet: "reduce all the unwanted column from all the
#: transaction table" — scoped by Sayanth to **Sales Invoice, Taxes and Charges,
#: for now**.
#:
#: MEASURED BEFORE HIDING, because hiding a Section Break takes everything inside
#: it (the trap that nearly hid the price list in Step 4):
#:
#:   taxes_section      tax_category · taxes_and_charges · shipping_rule ·
#:                      incoterm · named_place
#:   section_break_40   the `taxes` rows table
#:
#: Safe, and here is why. `SALES VAT 15% - KATC` is `is_default = 1` on the
#: company, so the template applies WITHOUT anyone picking it — 2,200 of 2,349
#: submitted invoices carry it, and all 428 customers sit in tax category `Sales`.
#: shipping_rule, incoterm and named_place are used on **0** invoices.
#:
#: The computed VAT is NOT hidden: `total_taxes_and_charges` lives in
#: `section_break_43` and Grand Total in `totals`, both untouched. The invoice
#: still shows and still prints its VAT.
#:
#: ⚠️ THE TRADE-OFF, STATED: with the picker hidden an operator can no longer
#: change or clear the tax template on a one-off invoice. 149 submitted invoices
#: currently carry no template (mostly 2024 documents and returns). If a
#: zero-rated or export invoice is ever needed, someone with the field unhidden
#: has to raise it.
_TAXES_BLOCK = (
	"taxes_section",
	"tax_category",
	"taxes_and_charges",
	"shipping_rule",
	"incoterm",
	"named_place",
	"section_break_40",
	"taxes",
)

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
		*_TAXES_BLOCK,
		"project",
		"currency",
		"conversion_rate",
		"time_sheet_list",
		"timesheets",
		"total_billing_hours",
		"total_billing_amount",
		*_CURRENCY_SECTION,
	],
	"Sales Order": ["project", "currency", "conversion_rate", *_CURRENCY_SECTION],
	"Delivery Note": ["project", "currency", "conversion_rate", *_CURRENCY_SECTION],
	# No `project` here on purpose: Quotation is the ONE doctype in this set that
	# has no `project` field in v15. Listing it was a silent no-op — _hide_fields
	# skips a field it cannot find, so nothing errored and nothing was hidden.
	# Caught by test_every_hidden_field_exists, which is why that test is strict.
	"Quotation": ["currency", "conversion_rate", *_CURRENCY_SECTION],
	"Purchase Invoice": [
		"project",
		"currency",
		"conversion_rate",
		"use_transaction_date_exchange_rate",
		*_CURRENCY_SECTION,
	],
	# `use_transaction_date_exchange_rate` is Purchase INVOICE only — another
	# silent no-op the strict test caught.
	"Purchase Receipt": ["project", "currency", "conversion_rate", *_CURRENCY_SECTION],
	"Payment Entry": ["project"],
}

#: Item 10 of the client sheet — "Selling & Buying Module keep as below", read as
#: the ON-SCREEN FORM. It asks for three controls, in this order, immediately
#: above the item table: **update stock · selling price · store**. (The printed
#: layouts are item 6, separately.) The other four points the sheet lists — header
#: and party, totals, payment terms, everything else — are already ERPNext's own
#: order on all six doctypes, so only this trio actually moves.
#:
#: The price list belongs next to the stock decision anyway: the operator picking
#: what to charge is the same operator deciding whether this document moves stock.
#:
#: 🔴 THIS REPLACES A PAIR OF RULES THAT FOUGHT EACH OTHER. Step 4's `MOVE_AFTER`
#: pinned the price list immediately AFTER its anchor; the first cut of item 10
#: then moved `set_warehouse` before `items_section` and pulled the anchor out
#: from under it. Each `after_migrate` satisfied one rule by breaking the other,
#: so `field_order` OSCILLATED between migrations — and on Sales Invoice it pushed
#: `update_stock` past `items_section` entirely (index 41 against 39). Caught by a
#: test, not by reading the migrate log, which reported success both times.
#:
#: Expressed as ONE rule: place this whole sequence, contiguously, just before the
#: anchor. Fields a doctype does not have are skipped rather than listed as silent
#: no-ops — Quotation has neither a header warehouse nor `update_stock`.
#: The group LEADS with `custom_stock_pricing_section` (a Custom Field Section
#: Break created in setup.py). Without it the trio lands inside the hidden
#: `Currency and Price List` span on Sales Invoice and Quotation, which have no
#: section break of their own between that accordion and the items table — and
#: hiding a Section Break hides everything up to the next one.
GROUP_BEFORE = {
	"Sales Invoice": (
		["custom_stock_pricing_section", "update_stock", "selling_price_list", "set_warehouse"],
		"items_section",
	),
	"Sales Order": (
		["custom_stock_pricing_section", "selling_price_list", "set_warehouse"],
		"items_section",
	),
	"Delivery Note": (
		["custom_stock_pricing_section", "selling_price_list", "set_warehouse"],
		"items_section",
	),
	"Quotation": (["custom_stock_pricing_section", "selling_price_list"], "items_section"),
	"Purchase Invoice": (
		["custom_stock_pricing_section", "update_stock", "buying_price_list", "set_warehouse"],
		"items_section",
	),
	"Purchase Receipt": (
		["custom_stock_pricing_section", "buying_price_list", "set_warehouse"],
		"items_section",
	),
}

#: Item 4 — "keep all list view, report view sorting order should Id wise based
#: fiscal year".
#:
#: Every one of these sorts `modified DESC` today, so a document someone merely
#: opened jumps to the top. The names carry the year (`KSIN-26-0042`), so sorting
#: by `name DESC` puts the newest document of the current year first and keeps a
#: year's documents together — which is what "Id wise based fiscal year" asks for.
#:
#: This sets the DEFAULT only. A user can still re-sort a column, and their choice
#: is remembered per list in their own settings.
SORT_BY_NAME = (
	"Sales Invoice",
	"Sales Order",
	"Delivery Note",
	"Quotation",
	"Purchase Invoice",
	"Purchase Receipt",
	"Purchase Order",
	"Payment Entry",
	"Journal Entry",
	"Stock Entry",
	"Material Request",
	"Stock Reconciliation",
)


def setup_form_layout():
	"""Idempotent. Safe to re-run on every after_migrate."""
	_hide_fields()
	_group_before()
	_sort_lists_by_name()
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


def _group_before():
	"""Place a sequence of fields contiguously, in order, just before an anchor.

	One rule instead of two competing ones — see GROUP_BEFORE for what that cost.
	The Property Setter carries the WHOLE field list, so the order is rebuilt from
	live metadata; a hardcoded list silently drops whatever a later ERPNext adds.
	"""
	for doctype, (group, anchor) in GROUP_BEFORE.items():
		if not frappe.db.exists("DocType", doctype):
			continue

		meta = frappe.get_meta(doctype)
		# Custom fields ARE included here, unlike _hide_fields' view of the world:
		# the section break this group leads with is itself a Custom Field, and
		# leaving it out would drop it from field_order entirely.
		order = [df.fieldname for df in meta.fields]
		if anchor not in order:
			continue

		present = [f for f in group if f in order]
		if not present:
			continue

		# Already contiguous and immediately before the anchor?
		target = order.index(anchor) - len(present)
		if order[target : order.index(anchor)] == present:
			continue

		for fieldname in present:
			order.remove(fieldname)
		at = order.index(anchor)
		for offset, fieldname in enumerate(present):
			order.insert(at + offset, fieldname)

		_set_property(doctype, None, "field_order", json.dumps(order), "Text", for_doctype=True)


def _sort_lists_by_name():
	"""Default every transaction list to newest-document-first by NAME.

	`sort_field` and `sort_order` are DocType properties, not field properties, so
	they are set with `field_name = None` — the same shape `field_order` uses.
	"""
	for doctype in SORT_BY_NAME:
		if not frappe.db.exists("DocType", doctype):
			continue
		_set_property(doctype, None, "sort_field", "name", "Data", for_doctype=True)
		_set_property(doctype, None, "sort_order", "DESC", "Data", for_doctype=True)


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


def _set_property(doctype, fieldname, prop, value, property_type, for_doctype=False):
	"""Create or update one Property Setter.

	🔴 `for_doctype` is NOT optional decoration. `frappe.make_property_setter`
	defaults `doctype_or_field` to **"DocField"** when it is not given
	(frappe/__init__.py: `if not args.doctype_or_field: args.doctype_or_field =
	"DocField"`), and meta only applies DOCTYPE-level properties like `sort_field`
	and `sort_order` from rows marked "DocType".

	Measured: the first version of `_sort_lists_by_name` wrote twelve rows with
	`doctype_or_field = "DocField"` and `field_name = NULL`. Every row inserted
	cleanly, the migrate reported success, and `Meta.sort_field` stayed
	`modified DESC` on all twelve doctypes. A silent no-op that looked done.
	"""
	existing = frappe.db.get_value(
		"Property Setter",
		{"doc_type": doctype, "field_name": fieldname, "property": prop},
		["name", "value", "doctype_or_field"],
		as_dict=True,
	)
	if existing:
		wanted = "DocType" if for_doctype else "DocField"
		if str(existing.value) != str(value):
			frappe.db.set_value("Property Setter", existing.name, "value", value)
		# Repair a row written before this flag existed, rather than leaving it inert.
		if existing.doctype_or_field != wanted:
			frappe.db.set_value("Property Setter", existing.name, "doctype_or_field", wanted)
		return

	args = {
		"doctype": doctype,
		"fieldname": fieldname,
		"property": prop,
		"value": value,
		"property_type": property_type,
	}
	if for_doctype:
		args["doctype_or_field"] = "DocType"

	frappe.make_property_setter(args, validate_fields_for_doctype=False)
