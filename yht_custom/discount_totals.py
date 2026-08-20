# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Item-wise discount, consolidated for print (MoM §2.3, plan step 5.5).

The *entry* half of this requirement was never missing. ERPNext already carries
`discount_percentage` and `discount_amount` on every selling row, and the client
uses them heavily — measured on the live site:

    Sales Invoice   4,935 rows carry a row discount
    Delivery Note   2,820
    Sales Order     2,636
    Quotation       2,327

What was missing is the *consolidated total*. The three print formats already
referenced `doc.custom_total_line_item_discount`, but no such field had ever been
created, so the "Line Discounts" row silently never rendered — a template reading
a field that does not exist is not an error in Jinja, it is an empty string.

ONE source of truth, deliberately. `line_discount_total` computes the figure from
the rows; the print formats call it through the Jinja helper, and the stored
Custom Field is a materialised copy of the same function's output written on
validate. The print formats do NOT read the stored field, so every historical
document prints a correct total with no backfill and no writes to submitted
documents. The field exists only so the number can be filtered and reported on.

Rate delta, not `discount_amount`. `(price_list_rate - rate) * qty` also catches
a rate typed straight over the price-list rate, which leaves `discount_amount` at
zero. On this site the two agree exactly today — SAR 74,884,245.13 across 4,935
Sales Invoice rows, with 0 rows at a zero price-list rate — so this costs nothing
now and stays right when someone edits a rate by hand.
"""

import frappe
from frappe.utils import flt

#: Selling documents that carry item-wise discounts and a printed total.
DISCOUNT_DOCTYPES = ("Sales Invoice", "Sales Order", "Delivery Note", "Quotation")

TOTAL_FIELD = "custom_total_line_item_discount"


def line_discount(row) -> float:
	"""Money given away on one row, in the document's currency.

	Falls back to `discount_amount` when there is no price-list rate to measure
	against — an item priced entirely by hand has nothing to be a discount from,
	but an operator may still have typed one.
	"""
	price_list_rate = flt(row.get("price_list_rate"))
	rate = flt(row.get("rate"))
	qty = flt(row.get("qty"))

	if price_list_rate > 0:
		return flt((price_list_rate - rate) * qty)

	return flt(flt(row.get("discount_amount")) * qty)


def line_discount_total(doc) -> float:
	"""Consolidated item-wise discount for the whole document.

	Deliberately excludes the header discount (`doc.discount_amount`): that one is
	applied to the document as a whole, is already printed on its own line, and
	adding the two together would present one number that reconciles against
	nothing.
	"""
	return flt(sum(line_discount(row) for row in (doc.get("items") or [])))


def set_line_discount_total(doc, method=None):
	"""Materialise the total onto the document. Registered on `validate`.

	doc_events for `validate` run AFTER the controller's own validate, so
	`calculate_taxes_and_totals` has already settled every rate by the time this
	reads them.
	"""
	if doc.meta.get_field(TOTAL_FIELD):
		doc.set(TOTAL_FIELD, line_discount_total(doc))


#: Item rows whose grid should offer a discount column.
DISCOUNT_ITEM_DOCTYPES = (
	"Sales Invoice Item",
	"Sales Order Item",
	"Delivery Note Item",
	"Quotation Item",
)


def setup_discount_grid_columns() -> dict:
	"""Put `discount_percentage` in the item grid on every selling document.

	"Item-wise discount entry" was already possible — the field has always existed
	behind the row's expand arrow, which is how 4,935 Sales Invoice rows got one.
	It was not *visible*, so an operator had to know it was there. These grids
	carry four to six columns today, so a sixth fits without pushing anything out.

	Idempotent, and it only ever raises the flag: a column somebody removed by
	hand stays removed only until the next migrate, which is the same contract
	every other provisioning step here honours.
	"""
	applied, already, failed = 0, 0, []

	for doctype in DISCOUNT_ITEM_DOCTYPES:
		if not frappe.get_meta(doctype).get_field("discount_percentage"):
			failed.append(f"{doctype}: no discount_percentage field")
			continue

		existing = frappe.db.get_value(
			"Property Setter",
			{"doc_type": doctype, "field_name": "discount_percentage", "property": "in_list_view"},
			["name", "value"],
			as_dict=True,
		)
		if existing:
			if str(existing.value) != "1":
				frappe.db.set_value("Property Setter", existing.name, "value", "1")
				applied += 1
			else:
				already += 1
			continue

		try:
			# An args DICT — the positional form belongs to a different function
			# and raises "got multiple values for argument
			# 'validate_fields_for_doctype'".
			frappe.make_property_setter(
				{
					"doctype": doctype,
					"fieldname": "discount_percentage",
					"property": "in_list_view",
					"value": "1",
					"property_type": "Check",
				},
				is_system_generated=True,
			)
			applied += 1
		except Exception as e:
			failed.append(f"{doctype}: {type(e).__name__}: {e}")

	if failed:
		frappe.log_error("\n".join(failed), "yht_custom: discount grid columns")

	return {"applied": applied, "already": already, "failed": failed}
