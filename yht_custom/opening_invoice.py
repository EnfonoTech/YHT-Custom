# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Carry a customer PO number and remarks through the Opening Invoice Creation Tool.

WHY AN OVERRIDE AND NOT A `doc_event`.
`OpeningInvoiceCreationTool.get_invoice_dict`
(`erpnext/accounts/doctype/opening_invoice_creation_tool/opening_invoice_creation_tool.py:179`)
assembles the invoice dict itself and offers NO extension point — no `run_method`,
no `get_hooks`, nothing. A `Sales Invoice` doc_event cannot stand in either: by the
time that invoice validates, the tool row it came from is out of scope. Subclassing
the controller is the only place where the ROW and the INVOICE exist together.

FIELD MAPPING — the destination is NOT the same fieldname on both sides:

    custom_po_no    -> Sales Invoice `po_no`   ("Customer's Purchase Order")
                    -> Purchase Invoice `bill_no` ("Supplier Invoice No")
    custom_remarks  -> `remarks` on both (Small Text on each)

The tool serves both invoice types from one child table, so a single PO column has
to land on whichever field that type actually uses. Writing `po_no` onto a Purchase
Invoice would silently go nowhere.

Empty values are skipped rather than written as "", so a blank column never
overwrites anything erpnext already set.
"""

import frappe
from frappe.utils import cstr

from erpnext.accounts.doctype.opening_invoice_creation_tool.opening_invoice_creation_tool import (
	OpeningInvoiceCreationTool,
)

#: Row fieldname -> (Sales Invoice fieldname, Purchase Invoice fieldname).
FIELD_MAP = {
	"custom_po_no": ("po_no", "bill_no"),
	"custom_remarks": ("remarks", "remarks"),
}


class YHTOpeningInvoiceCreationTool(OpeningInvoiceCreationTool):
	def get_invoice_dict(self, row=None):
		invoice = super().get_invoice_dict(row=row)
		if not row or not invoice:
			return invoice

		is_sales = invoice.get("doctype") == "Sales Invoice"

		for source, (sales_field, purchase_field) in FIELD_MAP.items():
			value = cstr(row.get(source)).strip()
			if not value:
				continue
			invoice[sales_field if is_sales else purchase_field] = value

		return invoice
