# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Expense Purchase Invoice.

## What the MoM asked for, and what the data actually showed

The MoM records expenses as being posted "through a Journal Entry with manually
keyed VAT", and asks for a separate Expense Invoice. The data on the legacy site
did not support that premise: `Record Expenses` already created real Purchase
Invoices — the `KSEPI-` series held 769 submitted invoices worth SAR 429,968.93,
each carrying a proper purchase tax template — so input VAT was already flowing
natively. Only 12 of 1,230 submitted Journal Entries touched a VAT account.

So the accounting output was broadly right. The **mechanism** was wrong, in four
ways:

1. A **wrapper doctype** shadowing the invoice it created: two documents and two
   numbering series per expense, with counts that did not even agree (356 wrapper
   rows against 769 invoices).
2. **One dummy item on every row** — `GENERAL ITEMS` / "Generic item for all" —
   so expense analysis by item was impossible and the real classification lived
   only in the expense account.
3. **`paid_through` conflated booking with paying**: payables, bank and cash
   appeared on consecutive rows, so cash-paid expenses never reached the supplier
   ledger.
4. Junk schema: a `purchase_series` Select carrying 60+ series for other group
   entities, `customer_name` typed `Link → Employee`, `asset_items`
   `Link → Item`.

## The design

**A flagged Purchase Invoice. No wrapper doctype.** Verified against this install
before choosing it:

* `Purchase Invoice Item.item_code` is **`reqd = 0`** while `item_name` is
  `reqd = 1`, so **itemless expense rows are natively supported** — which is what
  removes the dummy item without inventing a master per expense type.
* `Buying Settings` has `po_required = No` and `pr_required = No`, so an expense
  invoice stands alone.
* 60 leaf expense accounts already exist and are well structured.

`custom_expense_head` on the header stamps every row's `expense_account`, which is
the one thing users genuinely liked about the wrapper — a single field to pick the
expense — kept without the wrapper. Payment stays a Payment Entry, or ERPNext's
own `is_paid` + `cash_bank_account` for a genuine one-step cash expense.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

from yht_custom import features

#: 🔴 KSEPI-, not KSEXP- — corrected 2026-08-26. The client has 889 expense
#: invoices already named ``KSEPI-`` (counters KSEPI-24- 165, -25- 563, -26- 227);
#: ``KSEXP-`` was invented here and has ZERO documents. Continuing the client's own
#: convention is the whole rationale for the series design, and this broke it.
EXPENSE_SERIES = "KSEPI-.YY.-.####"


#: What makes a naming series an EXPENSE series — CR-012.
#:
#: 🔴 MEASURED, AND IT IS WHY CR-012 EXISTS. On `yht-khobhar` 2026-09-26,
#: `custom_is_expense_invoice` was 0 on **all 3,614** Purchase Invoices while
#: **384** of them carried an expense series: `KSEPI-.YY.-.####` (378),
#: `KSEPI-25-.####` (1), `KSEPI-26-.####` (5), plus 540 legacy rows under
#: `.{custom_company_series_abbr}.EPI-…`. The most recent was `KSEPI-26-0256`,
#: created 2026-08-31.
#:
#: So the flag was never the way anybody classified an expense. Operators pick the
#: `KSEPI-` series out of the naming-series dropdown and never see the checkbox,
#: which means the entire expense flow — `update_stock = 0`, the expense head
#: stamped onto every row, the stock-item guard — has NEVER ONCE RUN in
#: production. "Expense invoices post as plain Purchase Invoices", exactly as the
#: client reported it.
#:
#: Matching on `EPI-` is deliberately narrow and was checked against every series
#: on the site: the purchase series read `.PI-24-`, `KSPI-`, `KSPR-`, `KSXI-` and
#: `.PR-…`, none of which contains `EPI-`.
EXPENSE_SERIES_MARKER = "EPI-"


def _is_expense_series(series: str) -> bool:
	return EXPENSE_SERIES_MARKER in cstr(series).upper()


def _is_expense(doc) -> bool:
	return bool(cint(doc.get("custom_is_expense_invoice")))


def derive_expense_flag(doc, method=None):
	"""CR-012 — an expense series IS the classification. `before_validate`, first.

	The reverse of `set_expense_series`, and the pair is what makes the
	classification stick whichever end the operator starts from: tick the box and
	the series follows (`before_insert`), or pick the series and the box follows
	(here).

	🔴 IT ONLY EVER SETS, NEVER CLEARS. Un-ticking a flagged invoice whose series
	happens not to match is a legitimate correction — an ordinary purchase
	mis-keyed onto the expense counter, say — and a handler that re-derived the
	flag on every save would make that correction impossible to keep.

	Registered AHEAD of `expense_invoice.before_validate` in `hooks.py`, which is
	the whole point: the shaping step reads this flag, so deriving it afterwards
	would leave it one save behind.

	Behind `cr_012_expense_backfill`. On a site where 384 invoices are about to
	start behaving like expense invoices for the first time, "deployed" and "in
	effect" have to be two separate events — `validate` refuses a stock item on an
	expense invoice, and an existing DRAFT that was mis-keyed will now say so.
	"""
	if not features.enabled("cr_012_expense_backfill"):
		return
	if not doc.meta.has_field("custom_is_expense_invoice"):
		return
	if _is_expense(doc):
		return
	if _is_expense_series(doc.get("naming_series")) or _is_expense_series(doc.get("name")):
		doc.custom_is_expense_invoice = 1


# --------------------------------------------------------------- lifecycle


def before_validate(doc, method=None):
	"""Shape an expense invoice: no stock, expense head stamped onto every row."""
	if not _is_expense(doc):
		return

	# An expense invoice never moves stock. Forced rather than merely defaulted,
	# because a stock-updating expense invoice would post to a warehouse account
	# and silently corrupt inventory value.
	doc.update_stock = 0

	# Discard the blank starter row frappe adds to a new form.
	#
	# `shape()` in expense_invoice.js stamps the expense head onto every row including that
	# one, which makes it non-empty, so ERPNext's own "drop empty rows" pass keeps it and the
	# document posts a zero line. A row with nothing to say — no description, no item, no
	# amount — is not an expense.
	blank = [
		row
		for row in doc.get("items") or []
		if not (row.get("item_name") or row.get("description") or row.get("item_code"))
		and not flt(row.get("rate"))
		and not flt(row.get("amount"))
	]
	for row in blank:
		doc.get("items").remove(row)
	if blank:
		for idx, row in enumerate(doc.get("items") or [], start=1):
			row.idx = idx

	head = doc.get("custom_expense_head")
	for row in doc.get("items") or []:
		if head and not row.get("expense_account"):
			row.expense_account = head
		# Expense rows are one line each — quantity is meaningless for rent or a
		# licence renewal, and a blank qty fails ERPNext's own validation.
		if not flt(row.get("qty")):
			row.qty = 1

		# ...and so is a unit of measure. `Purchase Invoice Item.uom` is `reqd = 1`, so
		# without this an operator typing "Ramadan campaign — printing" is stopped by
		# "In Items, UOM is required in every row" and has to pick a unit for a service.
		# Found while capturing the training video: the guide says an expense row is a
		# description and an amount, and this is what makes that true.
		if not row.get("uom"):
			row.uom = _default_uom()
		if not row.get("stock_uom"):
			row.stock_uom = row.uom
		if not flt(row.get("conversion_factor")):
			row.conversion_factor = 1


def _default_uom() -> str:
	"""A unit for a line that has no physical unit.

	Prefers Stock Settings' default so a site that standardised on something else is
	respected, then ``Nos``, then whatever UOM exists — the field is mandatory, so
	returning nothing is not an option.
	"""
	configured = frappe.db.get_single_value("Stock Settings", "stock_uom")
	if configured and frappe.db.exists("UOM", configured):
		return configured
	if frappe.db.exists("UOM", "Nos"):
		return "Nos"
	return frappe.db.get_value("UOM", {}, "name")


def validate(doc, method=None):
	"""Guard the two things that make an expense invoice wrong if missed."""
	if not _is_expense(doc):
		return

	if not doc.get("items"):
		frappe.throw(_("Add at least one expense line."), title=_("Nothing to Post"))

	missing = [row.idx for row in doc.get("items") or [] if not row.get("expense_account")]
	if missing:
		frappe.throw(
			_("Rows {0} have no expense account. Set the Expense Head on the invoice, or fill each row.").format(
				", ".join(str(i) for i in missing)
			),
			title=_("Expense Account Required"),
		)

	# A stock item on an expense invoice is almost always a mis-flagged purchase:
	# it would expense inventory straight to P&L instead of capitalising it.
	stock_rows = []
	for row in doc.get("items") or []:
		if row.get("item_code") and frappe.db.get_value("Item", row.item_code, "is_stock_item"):
			stock_rows.append(f"{row.idx} ({row.item_code})")
	if stock_rows:
		frappe.throw(
			_("Rows {0} carry stock items. Use an ordinary Purchase Invoice with a Purchase Receipt for goods.").format(
				", ".join(stock_rows)
			),
			title=_("Stock Item on an Expense Invoice"),
		)


def on_submit(doc, method=None):
	"""No custom posting — ERPNext's own GL entries are already correct.

	Documented explicitly because the legacy wrapper is exactly what happens when
	someone decides otherwise: the tax template handles input VAT, the supplier
	payable is credited, and the expense accounts are debited. Nothing to add.
	"""
	return


# ------------------------------------------------------------------- setup


#: Custom fields that make a Purchase Invoice an expense invoice.
EXPENSE_CUSTOM_FIELDS = [
	{
		"fieldname": "custom_is_expense_invoice",
		"label": "Is Expense Invoice",
		"fieldtype": "Check",
		"insert_after": "is_return",
		"in_standard_filter": 1,
		"description": "An expense against a service or overhead, not a purchase of stock.",
	},
	{
		"fieldname": "custom_expense_head",
		"label": "Expense Head",
		"fieldtype": "Link",
		"options": "Account",
		"insert_after": "custom_is_expense_invoice",
		"depends_on": "eval:doc.custom_is_expense_invoice",
		"description": "Stamped onto every line that has no expense account of its own.",
	},
]


def setup_expense_invoice():
	"""Provision the fields, the series and the form filter. Idempotent."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields({"Purchase Invoice": EXPENSE_CUSTOM_FIELDS}, ignore_validate=True)

	# The Expense Head picker must only offer expense leaves.
	frappe.db.set_value(
		"Custom Field",
		{"dt": "Purchase Invoice", "fieldname": "custom_expense_head"},
		"link_filters",
		'[["Account","root_type","=","Expense"],["Account","is_group","=",0]]',
		update_modified=False,
	)

	_unhide_cash_payment_fields()
	_add_expense_series()
	_restore_expense_standard_filter()


def _unhide_cash_payment_fields():
	"""Restore `is_paid` and `cash_bank_account`.

	Legacy Property Setters hid and read-only'd both — that is why the old wrapper
	needed its own `paid_through` field, and why cash expenses never reached the
	supplier ledger. These two are ERPNext's correct answer for a one-step cash
	expense, so they come back.
	"""
	for fieldname in ("is_paid", "cash_bank_account", "mode_of_payment"):
		for prop in ("hidden", "read_only"):
			row = frappe.db.get_value(
				"Property Setter",
				{"doc_type": "Purchase Invoice", "field_name": fieldname, "property": prop},
				"name",
			)
			if row:
				frappe.delete_doc("Property Setter", row, force=1, ignore_permissions=True)


def _restore_expense_standard_filter():
	"""Put `Is Expense Invoice` back in the list sidebar — CR-012's "in bulk" half.

	`EXPENSE_CUSTOM_FIELDS` asks for `in_standard_filter: 1`, but a Property Setter
	written on this site overrides the field with `0`, so the filter is absent from
	the Purchase Invoice list. That matters because the client's request is to
	correct existing entries IN BULK, and the bulk edit runs off a filtered list:
	with no filter there is no list to run it from.

	A Property Setter is deleted rather than flipped. `create_custom_fields`
	already re-applies the field's own `in_standard_filter`, so removing the
	override is enough, and leaving a `1` row behind would be a second opinion on
	the same setting.
	"""
	row = frappe.db.get_value(
		"Property Setter",
		{
			"doc_type": "Purchase Invoice",
			"field_name": "custom_is_expense_invoice",
			"property": "in_standard_filter",
		},
		["name", "value"],
		as_dict=True,
	)
	if row and cstr(row.value) != "1":
		frappe.delete_doc("Property Setter", row.name, force=1, ignore_permissions=True)


def backfill_expense_flag(commit: bool = False) -> dict:
	"""Set the flag on every invoice whose series says it is an expense — CR-012.

	    bench --site … execute yht_custom.expense_invoice.backfill_expense_flag --kwargs "{'commit': True}"

	🔴 THE FLAG ONLY. Not `update_stock`, not the rows' `expense_account`, and no
	re-post of anything. These are submitted, posted documents whose GL entries the
	module docstring above establishes were already broadly correct — the fault was
	that they were not RECOGNISABLE as expenses, and that is what a flag fixes.
	Re-shaping 384 posted invoices would be a different and far larger decision,
	and it is not this one.

	`update_modified=False`, for the same reason: this changes how a document is
	classified, not what it recorded.
	"""
	rows = frappe.get_all(
		"Purchase Invoice",
		filters={"custom_is_expense_invoice": 0},
		fields=["name", "naming_series"],
		limit=0,
	)
	targets = [r for r in rows if _is_expense_series(r.naming_series) or _is_expense_series(r.name)]

	if commit:
		for row in targets:
			frappe.db.set_value(
				"Purchase Invoice", row.name, "custom_is_expense_invoice", 1, update_modified=False
			)
		frappe.db.commit()

	summary = {"committed": bool(commit), "scanned": len(rows), "flagged": len(targets)}
	print(frappe.as_json(summary, indent=1))
	return summary


def _add_expense_series():
	"""Add the expense series to the Purchase Invoice naming_series options."""
	meta_field = frappe.get_meta("Purchase Invoice").get_field("naming_series")
	if not meta_field:
		return

	existing = frappe.db.get_value(
		"Property Setter",
		{"doc_type": "Purchase Invoice", "field_name": "naming_series", "property": "options"},
		["name", "value"],
		as_dict=True,
	)
	current = (existing.value if existing else meta_field.options) or ""
	options = [o for o in current.split("\n") if o.strip()]
	if EXPENSE_SERIES in options:
		return

	options.append(EXPENSE_SERIES)
	value = "\n".join(options)
	if existing:
		frappe.db.set_value("Property Setter", existing.name, "value", value)
	else:
		frappe.make_property_setter(
			{
				"doctype": "Purchase Invoice",
				"fieldname": "naming_series",
				"property": "options",
				"value": value,
				"property_type": "Text",
			},
			validate_fields_for_doctype=False,
		)


def set_expense_series(doc, method=None):
	"""`before_insert` — an expense invoice takes the expense series.

	Runs after `branch_defaults.set_naming_series_from_branch`, deliberately: the
	branch series is the right default for a stock purchase, and this overrides it
	only for expenses.
	"""
	if not _is_expense(doc):
		return
	# 🔴 A RETURN KEEPS THE BRANCH'S RETURN SERIES. This function runs after
	# `branch_defaults.set_naming_series_from_branch` on purpose, so without this
	# guard it overwrote the debit-note series and a returned expense invoice drew
	# from the ordinary expense counter — measured: KSDBN- picked, then clobbered
	# back to the expense series. A debit note is a debit note whether the bill it
	# reverses was for stock or for rent.
	if cint(doc.get("is_return")):
		return
	doc.naming_series = EXPENSE_SERIES
