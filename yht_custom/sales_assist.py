# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""The last of the sales assist (MoM §2.5, plan 5.6).

MoM §2.5 asked for six things on the branch sales screen. Five were already
built: last rate sold to this customer and the recent price band (Price Assist),
customer outstanding and the credit-limit indicator, the cash/credit prompt, and
the warn-and-override over-limit route. This closes the sixth.

LIVE STOCK PER LINE NEEDED NO NEW CODE, ONLY UNHIDING. `actual_qty` — "Available
Qty at Warehouse" — already exists on all four selling item doctypes and ERPNext
already populates it: measured 12,467 Sales Invoice Item rows and 6,957 Sales
Order Item rows with **zero** nulls. It simply was not in the grid, so an operator
had to open the row to see it. Relabelled to "Stock" because a column header has
about twelve characters of room.

PAYMENT-DUE-DATE AUTOFILL WAS ALREADY WORKING, and the interesting part is why.
`Company.payment_terms` is `AS USUAL`, so ERPNext falls back to it for any customer
without their own template and computes `due_date` from it — only 176 of 2,344
submitted invoices have `due_date == posting_date`. But **401 of 428 customers
carry no payment terms of their own**, so almost every due date on this site comes
from one company-wide default rather than the terms actually agreed with that
customer. That is a data gap, not a code gap, so it is reported rather than
guessed at: `payment_terms_coverage()`.
"""

import frappe
from frappe.utils import cint, cstr, flt

#: (fieldname, label, read_only, columns) for the item grid, in the order the
#: client's sheet asks for them.
#:
#: 🔴 THE GRID HAS AN ELEVEN-UNIT BUDGET AND IT FAILS BY DROPPING COLUMNS SILENTLY.
#: `grid.js:setup_visible_columns` starts `total_colsize = 1`, adds each visible
#: column's width, and hits `if (total_colsize > 11) return false;` — which stops
#: the loop dead. Every column AFTER the one that overflows simply never renders,
#: with no error anywhere.
#:
#: That is exactly what unhiding UOM did. With ERPNext's own defaults the running
#: total went item_code 4 + qty 2 + uom 2 + discount 2 = 11, and `rate` took it to
#: 13 — so Rate, Amount, Warehouse and Stock all disappeared together and the grid
#: showed four columns. Nobody had ever set an explicit width, so the app had been
#: living inside whatever ERPNext's defaults happened to add up to.
#:
#: These widths are chosen to total exactly 10 (+1 = 11). Changing any one of them
#: means changing another, or the last column vanishes again.
GRID_LAYOUT = (
	("item_code", None, "0", "3"),
	("qty", None, "0", "1"),
	("uom", "UOM", "0", "1"),
	("rate", None, "0", "2"),
	("discount_percentage", "Discount %", "0", "1"),
	("amount", None, "0", "1"),
	("actual_qty", "Stock", "1", "1"),
)

#: The four selling item tables the layout applies to.
GRID_DOCTYPES = (
	"Sales Invoice Item",
	"Sales Order Item",
	"Delivery Note Item",
	"Quotation Item",
)

#: Shown by ERPNext default but not on the client's list, and there is no room for
#: it inside the eleven units. A branch user has one warehouse and it is already
#: set on the header.
GRID_HIDE = ("warehouse",)

#: Kept for the tests and callers that still read it: (doctype, fieldname, label,
#: read_only), derived from the layout above so the two can never disagree.
GRID_COLUMNS = tuple(
	(doctype, fieldname, label, read_only)
	for doctype in GRID_DOCTYPES
	for fieldname, label, read_only, _columns in GRID_LAYOUT
	if label
)


def setup_sales_assist_columns() -> dict:
	"""Lay out the item grid: which columns, in what order, how wide. Idempotent.

	Widths are set explicitly for every column because the grid's eleven-unit
	budget fails by silently dropping whatever comes after the overflow — see
	`GRID_LAYOUT`.
	"""
	applied, already, failed = 0, 0, []

	def _set(doctype, fieldname, prop, value, prop_type):
		nonlocal applied, already
		existing = frappe.db.get_value(
			"Property Setter",
			{"doc_type": doctype, "field_name": fieldname, "property": prop},
			["name", "value"],
			as_dict=True,
		)
		if existing:
			if cstr(existing.value) != cstr(value):
				frappe.db.set_value("Property Setter", existing.name, "value", value)
				applied += 1
			else:
				already += 1
			return
		try:
			# An args DICT — the positional form belongs to a different function.
			frappe.make_property_setter(
				{
					"doctype": doctype,
					"fieldname": fieldname,
					"property": prop,
					"value": value,
					"property_type": prop_type,
				},
				is_system_generated=True,
			)
			applied += 1
		except Exception as e:
			failed.append(f"{doctype}.{fieldname}.{prop}: {type(e).__name__}: {e}")

	for doctype in GRID_DOCTYPES:
		meta = frappe.get_meta(doctype)
		for fieldname, label, read_only, columns in GRID_LAYOUT:
			if not meta.get_field(fieldname):
				# Not every selling table carries every field; that is not an error.
				failed.append(f"{doctype}: no {fieldname}")
				continue
			_set(doctype, fieldname, "in_list_view", "1", "Check")
			_set(doctype, fieldname, "columns", columns, "Int")
			_set(doctype, fieldname, "read_only", read_only, "Check")
			if label:
				_set(doctype, fieldname, "label", label, "Data")

		for fieldname in GRID_HIDE:
			if meta.get_field(fieldname):
				_set(doctype, fieldname, "in_list_view", "0", "Check")

	if failed:
		frappe.log_error("\n".join(failed), "yht_custom: sales assist columns")

	return {"applied": applied, "already": already, "failed": failed}


# ------------------------------------------------------------------ reporting


def payment_terms_coverage() -> dict:
	"""Where due dates actually come from.

	    bench --site … execute yht_custom.sales_assist.payment_terms_coverage

	A due date computed from a company-wide default is not wrong, but it is not the
	customer's agreed terms either — and on this site that describes almost every
	invoice.
	"""
	customers = frappe.db.count("Customer")
	without = frappe.db.count("Customer", {"payment_terms": ["is", "not set"]})
	company = frappe.defaults.get_global_default("company")
	fallback = frappe.db.get_value("Company", company, "payment_terms") if company else None

	invoices = frappe.db.sql(
		"""SELECT COUNT(*) total,
		          SUM(due_date = posting_date) same_day,
		          SUM(due_date IS NULL) missing
		   FROM `tabSales Invoice` WHERE docstatus = 1""",
		as_dict=True,
	)[0]

	by_terms = frappe.db.sql(
		"""SELECT COALESCE(NULLIF(payment_terms, ''), '(none)') terms, COUNT(*) n
		   FROM `tabCustomer` GROUP BY terms ORDER BY n DESC LIMIT 8""",
		as_dict=True,
	)

	summary = {
		"customers": customers,
		"customers_without_own_terms": without,
		"company_fallback_template": fallback,
		"submitted_invoices": cint(invoices.total),
		"invoices_due_on_posting_date": cint(invoices.same_day),
		"invoices_without_a_due_date": cint(invoices.missing),
		"autofill_working": cint(invoices.total) > 0
		and cint(invoices.same_day) < cint(invoices.total),
		"customers_by_terms": {row.terms: row.n for row in by_terms},
	}
	print(frappe.as_json(summary, indent=1))
	return summary


def branch_stock(item_code: str, warehouse: str | None = None) -> float:
	"""Stock of one item, in the caller's branch. Used by tests and the console.

	Reads the same warehouse scope every other branch-aware surface reads, so it
	cannot disagree with the list views or the reports.
	"""
	from yht_custom import report_scope

	warehouses = report_scope.resolve_warehouses(warehouse)
	filters = {"item_code": item_code}
	if warehouses:
		filters["warehouse"] = ["in", warehouses]

	rows = frappe.get_all("Bin", filters=filters, fields=["actual_qty"])
	return flt(sum(flt(row.actual_qty) for row in rows))
