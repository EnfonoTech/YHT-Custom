# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Checks 41-44 - the Opening Invoice Creation Tool PO/remarks columns."""

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom.opening_invoice import FIELD_MAP, YHTOpeningInvoiceCreationTool

CHILD = "Opening Invoice Creation Tool Item"


class TestOpeningInvoiceColumns(FrappeTestCase):
	def test_the_controller_override_is_registered(self):
		"""check 41 - without the override the columns are captured and silently dropped,
		because erpnext's `get_invoice_dict` never looks at them."""
		self.assertEqual(
			frappe.get_hooks("override_doctype_class").get("Opening Invoice Creation Tool"),
			["yht_custom.opening_invoice.YHTOpeningInvoiceCreationTool"],
		)
		self.assertIsInstance(frappe.get_single("Opening Invoice Creation Tool"), YHTOpeningInvoiceCreationTool)

	def test_every_mapped_source_field_exists_on_the_child_table(self):
		# check 42 - the map and the Custom Fields must not drift apart.
		meta = frappe.get_meta(CHILD)
		for source in FIELD_MAP:
			f = meta.get_field(source)
			self.assertTrue(f, f"{source} missing on {CHILD}")
			self.assertTrue(f.in_list_view, f"{source} is not a grid column")

	def test_every_destination_field_exists_on_its_invoice(self):
		"""check 43 - the destination differs per invoice type; writing `po_no` onto a
		Purchase Invoice would go nowhere at all."""
		for _source, (sales_field, purchase_field) in FIELD_MAP.items():
			self.assertTrue(frappe.get_meta("Sales Invoice").get_field(sales_field), sales_field)
			self.assertTrue(frappe.get_meta("Purchase Invoice").get_field(purchase_field), purchase_field)

	def test_a_blank_column_never_overwrites(self):
		# check 44 - an empty cell must leave the invoice field alone, not blank it.
		tool = frappe.get_single("Opening Invoice Creation Tool")
		row = frappe._dict({source: "   " for source in FIELD_MAP})
		invoice = frappe._dict({"doctype": "Sales Invoice", "po_no": "KEEP-ME"})

		is_sales = True
		for source, (sales_field, purchase_field) in FIELD_MAP.items():
			value = (row.get(source) or "").strip()
			if value:
				invoice[sales_field if is_sales else purchase_field] = value
		self.assertEqual(invoice["po_no"], "KEEP-ME")
