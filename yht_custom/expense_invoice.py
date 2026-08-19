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
from frappe.utils import cint, flt

EXPENSE_SERIES = "KSEXP-.YY.-.####"


def _is_expense(doc) -> bool:
	return bool(cint(doc.get("custom_is_expense_invoice")))


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
	doc.naming_series = EXPENSE_SERIES
