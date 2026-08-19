# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Tests for the flow policy and the Expense Purchase Invoice."""

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import expense_invoice, sales_flow

BRANCH = "_Test YHT Flow Branch"
USER = "_test_yht_flow_user@example.invalid"


def _first(doctype, filters=None):
	return frappe.db.get_value(doctype, filters or {}, "name")


class TestFlowPolicy(FrappeTestCase):
	def setUp(self):
		self.company = _first("Company")
		self.warehouse = frappe.db.get_value(
			"Warehouse", {"company": self.company, "is_group": 0, "disabled": 0}, "name"
		)
		self.item = frappe.db.get_value("Item", {"is_stock_item": 1}, "name")
		if not (self.company and self.warehouse and self.item):
			self.skipTest("site lacks a company, warehouse or stock item")

		if not frappe.db.exists("Branch", BRANCH):
			frappe.get_doc({"doctype": "Branch", "branch": BRANCH}).insert(ignore_permissions=True)
		if not frappe.db.exists("User", USER):
			frappe.get_doc(
				{"doctype": "User", "email": USER, "first_name": "Flow", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		if frappe.db.exists("Branch Configuration", BRANCH):
			frappe.delete_doc("Branch Configuration", BRANCH, force=1, ignore_permissions=True)
		cfg = frappe.new_doc("Branch Configuration")
		cfg.branch = BRANCH
		cfg.company = self.company
		cfg.append("warehouse", {"warehouse": self.warehouse})
		cfg.append("user", {"user": USER, "role": "Branch User"})
		cfg.insert(ignore_permissions=True)
		frappe.clear_cache(user=USER)

	def tearDown(self):
		frappe.set_user("Administrator")
		if hasattr(frappe.local, "yht_branch_config_cache"):
			delattr(frappe.local, "yht_branch_config_cache")
		frappe.db.rollback()

	# ------------------------------------------------------- update_stock

	def test_branch_user_cannot_bill_and_ship_in_one_document(self):
		frappe.set_user(USER)
		si = frappe.new_doc("Sales Invoice")
		si.company = self.company
		si.update_stock = 1
		sales_flow.enforce_delivery_note_route(si)
		self.assertEqual(si.update_stock, 0)

	def test_manager_keeps_the_direct_route(self):
		frappe.set_user("Administrator")
		si = frappe.new_doc("Sales Invoice")
		si.company = self.company
		si.update_stock = 1
		sales_flow.enforce_delivery_note_route(si)
		self.assertEqual(si.update_stock, 1, "Administrator lost the direct-stock bypass")

	def test_purchase_invoice_stock_moves_to_the_receipt(self):
		frappe.set_user(USER)
		pi = frappe.new_doc("Purchase Invoice")
		pi.company = self.company
		pi.update_stock = 1
		sales_flow.enforce_purchase_receipt_route(pi)
		self.assertEqual(pi.update_stock, 0)

	def test_expense_invoice_is_exempt_from_the_receipt_rule(self):
		"""An expense invoice carries no stock, so the rule is meaningless for it."""
		frappe.set_user(USER)
		pi = frappe.new_doc("Purchase Invoice")
		pi.company = self.company
		pi.custom_is_expense_invoice = 1
		pi.update_stock = 0
		sales_flow.enforce_purchase_receipt_route(pi)
		self.assertEqual(pi.update_stock, 0)

	# ---------------------------------------------------------- zero rate

	def _dn(self, rate):
		dn = frappe.new_doc("Delivery Note")
		dn.company = self.company
		dn.set_warehouse = self.warehouse
		dn.append("items", {"item_code": self.item, "qty": 1, "rate": rate, "warehouse": self.warehouse})
		return dn

	def test_zero_rate_delivery_is_blocked(self):
		self.assertRaises(frappe.ValidationError, sales_flow.validate_delivery_note, self._dn(0))

	def test_priced_delivery_passes(self):
		sales_flow.validate_delivery_note(self._dn(10))  # must not raise

	def test_a_return_may_carry_a_zero_rate(self):
		"""A return mirrors the original document, nil lines included."""
		dn = self._dn(0)
		dn.is_return = 1
		sales_flow.validate_delivery_note(dn)  # must not raise


class TestExpenseInvoice(FrappeTestCase):
	def setUp(self):
		self.company = _first("Company")
		if not self.company:
			self.skipTest("no company")
		self.expense_account = frappe.db.get_value(
			"Account", {"company": self.company, "root_type": "Expense", "is_group": 0}, "name"
		)
		self.supplier = _first("Supplier")
		self.stock_item = frappe.db.get_value("Item", {"is_stock_item": 1}, "name")
		if not (self.expense_account and self.supplier):
			self.skipTest("site lacks an expense account or supplier")

	def tearDown(self):
		frappe.db.rollback()

	def _expense(self, with_head=True):
		pi = frappe.new_doc("Purchase Invoice")
		pi.company = self.company
		pi.supplier = self.supplier
		pi.custom_is_expense_invoice = 1
		if with_head:
			pi.custom_expense_head = self.expense_account
		pi.append("items", {"item_name": "Showroom electricity", "rate": 1200})
		return pi

	def test_fields_are_provisioned(self):
		for fieldname in ("custom_is_expense_invoice", "custom_expense_head"):
			self.assertTrue(
				frappe.db.exists("Custom Field", {"dt": "Purchase Invoice", "fieldname": fieldname}),
				fieldname,
			)

	def test_itemless_rows_are_supported(self):
		"""The whole design rests on item_code being optional — pin it."""
		field = frappe.get_meta("Purchase Invoice Item").get_field("item_code")
		self.assertFalse(field.reqd, "item_code became mandatory; the expense design needs revisiting")
		self.assertTrue(frappe.get_meta("Purchase Invoice Item").get_field("item_name").reqd)

	def test_expense_head_is_stamped_onto_rows(self):
		pi = self._expense()
		expense_invoice.before_validate(pi)
		self.assertEqual(pi.items[0].expense_account, self.expense_account)

	def test_qty_defaults_to_one(self):
		"""Quantity is meaningless for rent, and a blank qty fails ERPNext."""
		pi = self._expense()
		expense_invoice.before_validate(pi)
		self.assertEqual(pi.items[0].qty, 1)

	def test_update_stock_is_forced_off(self):
		pi = self._expense()
		pi.update_stock = 1
		expense_invoice.before_validate(pi)
		self.assertEqual(pi.update_stock, 0)

	def test_a_row_without_an_expense_account_is_rejected(self):
		pi = self._expense(with_head=False)
		expense_invoice.before_validate(pi)
		self.assertRaises(frappe.ValidationError, expense_invoice.validate, pi)

	def test_a_stock_item_is_rejected(self):
		"""Expensing inventory to P&L instead of capitalising it is the bug this
		catches — almost always a mis-flagged ordinary purchase."""
		if not self.stock_item:
			self.skipTest("no stock item")
		pi = self._expense()
		pi.items[0].item_code = self.stock_item
		expense_invoice.before_validate(pi)
		self.assertRaises(frappe.ValidationError, expense_invoice.validate, pi)

	def test_an_empty_expense_invoice_is_rejected(self):
		pi = frappe.new_doc("Purchase Invoice")
		pi.company = self.company
		pi.supplier = self.supplier
		pi.custom_is_expense_invoice = 1
		self.assertRaises(frappe.ValidationError, expense_invoice.validate, pi)

	def test_ordinary_purchase_invoices_are_untouched(self):
		pi = frappe.new_doc("Purchase Invoice")
		pi.company = self.company
		pi.supplier = self.supplier
		pi.update_stock = 1
		expense_invoice.before_validate(pi)
		self.assertEqual(pi.update_stock, 1, "the expense hook altered a normal purchase invoice")
		expense_invoice.validate(pi)  # must not raise

	def test_expense_series_is_registered_and_applied(self):
		options = frappe.db.get_value(
			"Property Setter",
			{"doc_type": "Purchase Invoice", "field_name": "naming_series", "property": "options"},
			"value",
		) or ""
		self.assertIn(expense_invoice.EXPENSE_SERIES, options.split("\n"))

		pi = self._expense()
		pi.naming_series = "SOMETHING-ELSE-"
		expense_invoice.set_expense_series(pi)
		self.assertEqual(pi.naming_series, expense_invoice.EXPENSE_SERIES)

	def test_cash_payment_fields_are_visible_again(self):
		"""Legacy Property Setters hid is_paid and cash_bank_account, which is why
		the old wrapper invented paid_through."""
		for fieldname in ("is_paid", "cash_bank_account"):
			for prop in ("hidden", "read_only"):
				self.assertFalse(
					frappe.db.exists(
						"Property Setter",
						{"doc_type": "Purchase Invoice", "field_name": fieldname, "property": prop},
					),
					f"{fieldname}.{prop} setter is still present",
				)
