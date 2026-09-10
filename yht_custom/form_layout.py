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
from frappe import _

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
	# Client sheet item 29 — the Address form the client asked for keeps the
	# postal fields and drops the contact ones. Email / Phone / Fax are captured
	# on the Contact, never on the Address, on all 578 rows.
	#
	# `address_title` is NOT here: it is GATED rather than hidden outright — see
	# ADDRESS_TITLE_GATE. The ORDER half of the item lives in
	# `field_layout.FIELD_MOVES["Address"]`.
	#
	# Nothing in item 29 writes `reqd` or `mandatory_depends_on` — `country` stays
	# required as shipped.
	"Address": ["email_id", "phone", "fax"],
}

#: Client sheet item 29 — Address Title, hidden in the flow the client works in
#: and back on the form in the one state frappe refuses to save without it.
#:
#: 🔴 A HARD HIDE MAKES A LINK-LESS NEW ADDRESS UNSAVEABLE, POINTING AT A FIELD
#: THAT IS NOT ON THE SCREEN. `frappe/contacts/doctype/address/address.py`
#: throws *"Address Title is mandatory."* whenever `address_title` is blank and
#: the document carries no `links` row, and `saudi_address.before_insert` fills
#: it from `custom_short_address` **only when the short code is present** — which
#: `saudi_address` deliberately does not require. So: *New Address* from the
#: Address list, no party linked yet, Short Address left blank → the save is
#: refused naming an invisible field. That is precisely the failure item 33 went
#: to some trouble to avoid on Payment Entry, reproduced on Address.
#:
#: `depends_on` rather than `hidden` reproduces the client's ask — in the normal
#: flow (create the address from a Customer, or type the Short Address) they
#: never see it — and keeps the field reachable in the one state where the
#: controller insists on it. Client-side only, so nothing about naming or
#: validation changes.
ADDRESS_TITLE_GATE = ("Address", "address_title", "eval:!doc.custom_short_address")

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

#: Client sheet item 24 — "document title = voucher number".
#:
#: The mechanism is a DocType-level `title_field = "name"` Property Setter, NOT a
#: default on the `title` field. `frappe/model/meta.py::get_title_field()` returns
#: `self.title_field or ("title" if has_field else "name")`, and
#: `Document.get_title()` is `self.get(self.meta.get_title_field())` — so the form
#: header and the list subject both read `doc.name`, for EXISTING documents as
#: well as new ones, with nothing written to any row.
#:
#: A `default` on the `title` field was checked and rejected twice over:
#:
#: * `Document.set_title_field()` is guarded by
#:   `if self.meta.get("title_field") == "title"`, which is FALSE on **Sales
#:   Order** (it ships `title_field = "customer_name"`), and it would not touch a
#:   single one of the ~2,354 already-submitted invoices.
#: * **Payment Entry** and **Journal Entry** overwrite `title` from their
#:   controllers on every save (`payment_entry.set_title()`,
#:   `journal_entry.self.title = self.get_title()`), so a field default there is
#:   dead on arrival.
#:
#: Side effect, accepted: with `title_field != "title"`, `set_title_field()`
#: becomes a no-op, so the stored `title` column stops being rewritten on save.
#: Existing values stay put — nothing to migrate, nothing to undo, and reverting
#: is one Property Setter delete.
TITLE_AS_VOUCHER_NO = (
	"Sales Invoice",
	"Sales Order",
	"Delivery Note",
	"Quotation",
	"Purchase Invoice",
	"Purchase Receipt",
	"Payment Entry",
	"Journal Entry",
)

#: ⚠️ JOURNAL ENTRY IS COVERED ON THE FORM AND **NOT** IN PYTHON, and the difference
#: is worth knowing before someone "fixes" it.
#: `erpnext/accounts/doctype/journal_entry/journal_entry.py:249` OVERRIDES
#: `get_title()` outright — `return self.pay_to_recd_from or self.accounts[0].account`
#: — so `doc.get_title()` keeps returning the party name however `title_field` is set.
#: No Property Setter can win that, and nothing short of `override_doctype_class`
#: could.
#: What the client asked for is unaffected: `frappe/public/js/frappe/form/toolbar.js:48-50`
#: renders `doc[meta.title_field] || docname`, reading the FIELD rather than calling
#: `get_title()`, so the desk header and the list subject both show the voucher number.
#: Confirmed by opening the form, not inferred. The Python title is used by
#: notifications and link previews, which is why Journal Entry keeps its party name
#: there — an acceptable split, and a deliberate one.

#: Client sheet item 25 — a standalone invoice opens with **Update Stock** ticked.
#:
#: 🔴 THE DEFAULT AND THE SERVER RULE SHIP TOGETHER. Neither is merged alone.
#: ERPNext already ships `Sales Invoice.update_stock` with
#: `depends_on: "eval:doc.items.every((item) => !item.dn_detail)"` and the
#: `pr_detail` twin on Purchase Invoice, so the checkbox is **hidden** — stronger
#: than read-only — the moment a row carries the stock-document link. And
#: `SalesInvoice.validate_delivery_note()` throws *"Stock cannot be updated
#: against Delivery Note {0}"* whenever `update_stock` is on and a row names one.
#:
#: `get_mapped_doc` applies field defaults to the target, so a bare `default = 1`
#: would give every invoice mapped from a Delivery Note `update_stock = 1`, hide
#: the box so the operator cannot untick it, and then refuse the save with an
#: error they cannot act on. `sales_flow.enforce_delivery_note_route` zeroes it
#: first, which is what makes the default safe.
UPDATE_STOCK_DEFAULT = ("Sales Invoice", "Purchase Invoice")

#: Client sheet item 33 — the Payment Entry tax block.
#:
#: Verified upstream field order (v15.119.2):
#:
#:   taxes_and_charges_section · purchase_taxes_and_charges_template ·
#:   sales_taxes_and_charges_template · column_break_55 ·
#:   apply_tax_withholding_amount · tax_withholding_category
#:   section_break_56 · taxes
#:   section_break_60 · base_total_taxes_and_charges · column_break_61 ·
#:   total_taxes_and_charges
#:   deductions_or_loss_section · deductions      <-- KEEP, itself a Section Break
#:
#: Because `deductions_or_loss_section` is a Section Break the hidden span ends
#: there, so "hiding a Section Break hides everything inside it" works FOR us and
#: deductions survive.
#:
#: 🔴 THE REQUIREMENT'S LIST AS WRITTEN IS SELF-DEFEATING.
#: `sales_taxes_and_charges_template` lives INSIDE `taxes_and_charges_section`, so
#: hiding that section hides the template whatever its own `hidden` says — and the
#: template carries `mandatory_depends_on: eval:doc.custom_prepayment_invoice`
#: from `zatca_vat_report`, which IS installed on this bench and WILL revert
#: anything we blank on its next migrate. Every prepayment Payment Entry would
#: become unsaveable with a mandatory error pointing at a field nobody can see —
#: precisely the failure the requirement asks to avoid. Hence `depends_on` on the
#: sections rather than `hidden`: it is client-side only, so `mandatory_depends_on`
#: still fires exactly as before.
PE_TAX_GATED_SECTIONS = ("taxes_and_charges_section", "section_break_56", "section_break_60")

#: Hidden outright, in either state. Withholding is not used on this site and a
#: purchase template is meaningless on a Receive entry.
PE_TAX_HIDDEN_FIELDS = (
	"purchase_taxes_and_charges_template",
	"apply_tax_withholding_amount",
	"tax_withholding_category",
)

#: The escape hatch. If this is missing, hidden, or itself inside one of the
#: gated sections, the whole design is unreachable and the item does not ship.
PE_PREPAYMENT_FLAG = "custom_prepayment_invoice"

#: Client sheet item 36 — split forward documents from returns in the list views.
#:
#: GATE DECISION Q9, which overrides the spec body: the CHEAP option ships.
#: `in_standard_filter = 1` on the EXISTING `is_return` Check — no new Custom
#: Field, no derived document-kind column, no 8,603-row backfill. It is literally
#: the control the client pointed at (`Is Expense Invoice`), and a Custom Field
#: that is later withdrawn leaves its column and its data behind (gotcha 22).
#:
#: `base_list.js::get_standard_filters()` SKIPS a field whose value is falsy, so
#: an unticked box applies no filter at all — that blank IS the "All". Which is
#: also why this item must never write a `default` onto `is_return`: a default of
#: 1 would open every one of these lists on returns only.
#:
#: Known limitation, ACCEPTED at the gate: a tick shows returns only, unticked
#: shows everything, so it cannot express "forward only". If the client rejects
#: that on `yht-test`, the Select is a follow-up rather than a rebuild.
RETURN_SPLIT_LISTS = ("Sales Invoice", "Delivery Note", "Purchase Invoice", "Purchase Receipt")


def setup_form_layout():
	"""Idempotent. Safe to re-run on every after_migrate."""
	_hide_fields()
	_gate_address_title()
	_group_before()
	_sort_lists_by_name()
	_default_branch_series()


def _gate_address_title():
	"""Item 29 — show Address Title only when there is no Short Address.

	The `hidden = 0` write is not decoration: an earlier cut of this item put
	`address_title` in HIDE_FIELDS, so any site that has already migrated it
	carries an `Address-address_title-hidden` Property Setter, and a `depends_on`
	cannot bring back a field that is hidden outright. Setting it back to 0 is
	what makes the gate reachable on those sites. See ADDRESS_TITLE_GATE.
	"""
	doctype, fieldname, condition = ADDRESS_TITLE_GATE
	if not frappe.db.exists("DocType", doctype):
		return
	meta = frappe.get_meta(doctype)
	if not meta.get_field(fieldname):
		return
	if not meta.get_field("custom_short_address"):
		# The gate reads a field that does not exist yet, which would evaluate
		# falsy and leave Address Title permanently on the form. Harmless, but say
		# so rather than shipping a condition nobody can satisfy.
		frappe.log_error(
			message=f"{doctype}.custom_short_address is missing; {fieldname} left ungated",
			title="yht_custom: address title gate",
		)
		return

	_set_property(doctype, fieldname, "hidden", "0", "Check")
	_set_property(doctype, fieldname, "depends_on", condition, "Code")


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


# ------------------------------------------------------------------- batch 3
#
# Each of the four below is registered as its OWN `PROVISIONING_STEPS` entry
# rather than called from `setup_form_layout`. `after_migrate` wraps every step
# in its own try/except/commit, so one item's exception cannot hide another's —
# which is exactly what bolting them into one function would do.


def setup_title_as_voucher_no():
	"""🔴 WITHDRAWN — DO NOT RUN. Kept only for the analysis written below it.

	Item 24 asked for the document title to read as the voucher number. This
	mechanism — a DocType-level `title_field = "name"` Property Setter — **empties
	every one of the eight transaction lists**. `list_view.js` resolves the subject
	column through `frappe.meta.get_docfield`, `name` has no DocField, and
	`get_header_html` throws, so the list renders zero rows. `yht_custom.patches.
	drop_title_as_voucher_no` deletes the rows from any site that already took them.

	It is unregistered — absent from `setup.py`'s imports, `PROVISIONING_STEPS` and
	`_imported()` — and fenced here as well, because "unregistered" is one careless
	`bench execute` away from being run anyway on a client site.

	The replacement has not been chosen. The client's own fallback is the cheap one:
	*"If its difficult change to voucher number, you can hide from entire."* That is
	`in_list_view = 0` on the `title` field, which touches no doctype-level property
	and cannot break the subject column. `frappe.listview_settings[dt].add_fields`
	with a formatter is the other candidate. Either is its own item.

	The body below the throw is what the upstream analysis cost and is why the
	function is not simply deleted:

	    for doctype in TITLE_AS_VOUCHER_NO:
	        _set_property(doctype, None, "title_field", "name", "Data", for_doctype=True)

	`for_doctype=True` was the non-obvious part — `frappe.make_property_setter`
	defaults `doctype_or_field` to "DocField", and `Meta` only reads DOCTYPE-level
	rows for `title_field`.
	"""
	frappe.throw(
		_(
			"setup_title_as_voucher_no is withdrawn: title_field = 'name' makes every "
			"transaction list render zero rows. See the docstring for the replacement."
		)
	)


def setup_update_stock_default():
	"""Item 25 — `update_stock` opens ticked on a standalone invoice.

	Ships with `sales_flow.enforce_delivery_note_route` /
	`enforce_purchase_receipt_route`, which zero it again whenever the goods have
	already moved. See UPDATE_STOCK_DEFAULT for why neither half works alone.
	"""
	for doctype in UPDATE_STOCK_DEFAULT:
		if not frappe.db.exists("DocType", doctype):
			continue
		if not frappe.get_meta(doctype).get_field("update_stock"):
			# A fieldname that does not exist is configured silently and the change
			# looks done for a week. Assert, never assume.
			continue
		_set_property(doctype, "update_stock", "default", "1", "Text")


def setup_payment_entry_tax_block():
	"""Item 33 — collapse the tax block unless this is a prepayment invoice.

	Three Section Breaks get `depends_on` rather than `hidden`, so a prepayment
	still reaches the `taxes` grid and the totals it needs to read a document
	that posts tax to the ledger. Three fields nobody wants in either state are
	hidden outright. `sales_taxes_and_charges_template` is deliberately left
	VISIBLE and its `mandatory_depends_on` deliberately left alone — see
	PE_TAX_GATED_SECTIONS.
	"""
	if not frappe.db.exists("DocType", "Payment Entry"):
		return

	meta = frappe.get_meta("Payment Entry")

	flag = meta.get_field(PE_PREPAYMENT_FLAG)
	if not flag or flag.hidden:
		# Without a reachable flag the whole block would be gated on something the
		# operator cannot tick, i.e. permanently gone. Report and change nothing.
		frappe.log_error(
			message=f"Payment Entry.{PE_PREPAYMENT_FLAG} is missing or hidden; item 33 not applied",
			title="yht_custom: payment entry tax block",
		)
		return

	if _section_of(meta, PE_PREPAYMENT_FLAG) in PE_TAX_GATED_SECTIONS:
		# The flag sits INSIDE a section we are about to gate on it, so ticking it
		# would be impossible once the gate is on. Same failure, one level deeper.
		frappe.log_error(
			message=f"Payment Entry.{PE_PREPAYMENT_FLAG} sits inside a gated section; item 33 not applied",
			title="yht_custom: payment entry tax block",
		)
		return

	for fieldname in PE_TAX_GATED_SECTIONS:
		field = meta.get_field(fieldname)
		if not field:
			continue
		current = field.depends_on or ""
		if PE_PREPAYMENT_FLAG in current:
			# Already gated. Re-combining would stack the expression a second time
			# on every migrate, which is what "combine rather than overwrite" turns
			# into when it is written carelessly.
			continue
		_set_property(
			"Payment Entry",
			fieldname,
			"depends_on",
			_combine_depends_on(current, PE_PREPAYMENT_FLAG),
			"Code",
		)

	for fieldname in PE_TAX_HIDDEN_FIELDS:
		if not meta.get_field(fieldname):
			continue
		_set_property("Payment Entry", fieldname, "hidden", "1", "Check")


def setup_return_split_filter():
	"""Item 36 — put the existing `is_return` Check in the list filter row.

	Gate decision Q9. No new field, no backfill; see RETURN_SPLIT_LISTS.
	"""
	for doctype in RETURN_SPLIT_LISTS:
		if not frappe.db.exists("DocType", doctype):
			continue
		if not frappe.get_meta(doctype).get_field("is_return"):
			continue
		_set_property(doctype, "is_return", "in_standard_filter", "1", "Check")


def _section_of(meta, fieldname):
	"""The Section Break a field currently belongs to, or None."""
	section = None
	for field in meta.fields:
		if field.fieldtype in ("Section Break", "Tab Break"):
			section = field.fieldname
		if field.fieldname == fieldname:
			return section
	return None


def _combine_depends_on(existing, flag):
	"""AND our gate onto whatever the doctype already carried.

	Overwriting would drop a shipped condition silently. Both shapes frappe
	accepts are handled: an `eval:` expression, and a bare fieldname.

	⚠️ KNOWN LIMIT, ACCEPTED. The caller short-circuits on
	`if PE_PREPAYMENT_FLAG in current`, a SUBSTRING test on the stored value —
	which is what stops the expression stacking a second copy of the gate on
	every migrate. The cost is that if a later ERPNext changes the SHIPPED
	`depends_on` on one of these sections, the stored Property Setter keeps the
	old combination and the new upstream rule is silently lost. Detecting that
	properly means storing the shipped value we combined FROM and comparing
	against it — a second Property Setter per field, or a marker inside the
	expression. Not built: these three are Section Breaks whose shipped
	`depends_on` is empty in v15.119.2, so there is nothing to lose yet, and a
	re-check belongs in the next ERPNext upgrade rather than here.
	"""
	existing = (existing or "").strip()
	if not existing:
		return f"eval:doc.{flag}"
	if existing.startswith("eval:"):
		return f"eval:({existing[len('eval:') :].strip()}) && doc.{flag}"
	return f"eval:doc.{existing} && doc.{flag}"


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

	⚠️ THE UPDATE PATH DOES NOT CLEAR THE DOCTYPE CACHE, AND THE INSERT PATH DOES.
	Updating an existing row goes through `frappe.db.set_value`, which skips
	`PropertySetter.validate` / `on_trash` and therefore the
	`frappe.clear_cache(doctype=…)` they run; `frappe.make_property_setter`
	inserts a document and gets it. Inside `bench migrate` the difference is
	invisible — migrate clears the cache anyway — but a `bench execute` of one
	provisioning step on a running site leaves the OLD meta live, so the change
	reads as a no-op until a restart or a `bench clear-cache`. Clear the cache
	yourself when calling a step by hand.
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
