# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Row 11 (2026-10-08) — a Sales Invoice or a Delivery Note straight from a Quotation.

ERPNext v15 offers only Create > Sales Order on a submitted Quotation
(`quotation.js:125`), although the server has shipped
`quotation.make_sales_invoice` for years — the Sales Invoice button therefore
calls that upstream mapper and nothing here. The Delivery Note has no upstream
mapper at all, so one lives below, shaped after `sales_order.make_delivery_note`
minus the back-links a Delivery Note Item has no field for: there is no
`quotation` / `qo_detail` on it, and `against_sales_order` stays empty because
there is no order.

Who this is for: counter customers at the OTHER branches, who buy without a
Sales Order. Khobar keeps its Sales Order flow — the buttons are additive, and
the item grid, taxes and `update_stock` rules that apply to any other Delivery
Note apply to this one.
"""

import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt


def _customer_of(quotation_name: str) -> str:
	quotation = frappe.db.get_value(
		"Quotation", quotation_name, ["quotation_to", "party_name"], as_dict=True
	)
	if not quotation:
		frappe.throw(_("Quotation {0} not found").format(quotation_name))
	if quotation.quotation_to != "Customer":
		# A Lead has no receivable account and no address to deliver to. ERPNext's
		# own Sales Order / Sales Invoice mappers create the Customer on the way;
		# a Delivery Note raised here does not, so say so instead of guessing.
		frappe.throw(
			_("This quotation is addressed to a {0}, not a Customer. Create the Sales Order or Sales Invoice first — that converts it — then raise the Delivery Note.").format(
				_(quotation.quotation_to or "Lead")
			)
		)
	return quotation.party_name


@frappe.whitelist()
def make_delivery_note(source_name, target_doc=None):
	"""Create > Delivery Note on a submitted Quotation."""
	if not frappe.has_permission("Delivery Note", "create"):
		frappe.throw(_("Not permitted to create a Delivery Note"), frappe.PermissionError)

	customer = _customer_of(source_name)

	def set_missing_values(source, target):
		target.customer = customer
		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

	def update_item(obj, target, source_parent):
		target.stock_qty = flt(obj.qty) * flt(obj.conversion_factor)
		# Cleared the way the upstream Quotation -> Sales Invoice mapper clears
		# it: `branch_defaults` stamps the branch's own cost centre on save.
		target.cost_center = None

	return get_mapped_doc(
		"Quotation",
		source_name,
		{
			"Quotation": {"doctype": "Delivery Note", "validation": {"docstatus": ["=", 1]}},
			"Quotation Item": {
				"doctype": "Delivery Note Item",
				"field_map": {"rate": "rate"},
				"postprocess": update_item,
				# An alternative line is an offer, not a thing to deliver — the
				# same rule the upstream Sales Invoice mapper applies.
				"condition": lambda row: not row.is_alternative,
			},
			"Sales Taxes and Charges": {"doctype": "Sales Taxes and Charges", "reset_value": True},
			"Sales Team": {"doctype": "Sales Team", "add_if_empty": True},
		},
		target_doc,
		set_missing_values,
	)
