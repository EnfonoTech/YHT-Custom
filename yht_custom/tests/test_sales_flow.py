# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Tests for the flow policy and the Expense Purchase Invoice."""

import json

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


class TestGetItemsFromSalesOrder(FrappeTestCase):
	"""The desk's "Get Items From > Sales Order" 417'd and left the invoice empty."""

	def _open_so(self):
		return frappe.db.get_value(
			"Sales Order",
			{"docstatus": 1, "status": ["not in", ["Closed", "On Hold"]], "per_billed": ["<", 99.99]},
			"name",
			order_by="creation desc",
		)

	def test_the_override_is_registered(self):
		"""`map_docs` resolves the override before calling, so the hook is the fix."""
		resolved = frappe.override_whitelisted_method(
			"erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice"
		)
		self.assertEqual(resolved, "yht_custom.sales_flow.make_sales_invoice_from_sales_order")

	def test_the_override_is_whitelisted(self):
		"""map_docs raises PermissionError if the resolved target is not whitelisted."""
		method = frappe.get_attr("yht_custom.sales_flow.make_sales_invoice_from_sales_order")
		self.assertIn(method, frappe.whitelisted)

	def test_args_in_the_third_slot_maps_items(self):
		"""🔴 THE REGRESSION, in the shape the desk actually sends it.

		`map_docs` calls `method(src, target_doc, args)`. Against ERPNext's own
		signature that dict lands on `ignore_permissions` and pydantic 417s.
		"""
		so = self._open_so()
		if not so:
			self.skipTest("no open Sales Order")
		make = frappe.get_attr("yht_custom.sales_flow.make_sales_invoice_from_sales_order")
		# A JSON STRING, which is what the desk posts. `get_mapped_doc` handles a str
		# or a Document; a raw dict reaches `target_doc.has_permission` and raises.
		target = json.dumps({"doctype": "Sales Invoice", "docstatus": 0})
		out = make(so, target, {"filtered_children": []})
		self.assertTrue(out.get("items"), "the desk's calling convention returned no items")
		for row in out.get("items"):
			self.assertTrue(row.get("so_detail"), "a mapped row must carry so_detail")

	def test_ignore_permissions_in_the_third_slot_still_works(self):
		"""ERPNext's own signature invites this, so the shim must not break it."""
		so = self._open_so()
		if not so:
			self.skipTest("no open Sales Order")
		make = frappe.get_attr("yht_custom.sales_flow.make_sales_invoice_from_sales_order")
		out = make(so, json.dumps({"doctype": "Sales Invoice", "docstatus": 0}), True)
		self.assertTrue(out.get("items"))

	def test_it_maps_the_same_items_as_erpnext(self):
		"""The shim forwards; it must not change what gets mapped."""
		so = self._open_so()
		if not so:
			self.skipTest("no open Sales Order")
		from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
		make = frappe.get_attr("yht_custom.sales_flow.make_sales_invoice_from_sales_order")
		theirs = [r.item_code for r in (make_sales_invoice(so).get("items") or [])]
		ours = [r.item_code for r in (make(so, None, {"filtered_children": []}).get("items") or [])]
		self.assertEqual(ours, theirs)


class TestSalesReturnEntryPoints(FrappeTestCase):
	"""A return gets its own way in, because it gets its own series."""

	def test_is_return_is_no_copy(self):
		"""🔴 THE REASON THIS NEEDED CODE AND NOT CONFIG.

		`create_new.js` applies `frappe.route_options` but skips `no_copy` fields, so a
		shortcut, a ?is_return=1 URL and frappe.new_doc(dt, {is_return: 1}) ALL land on a
		blank invoice with the box clear — measured on the site, all three. If this ever
		flips to 0 upstream, the JS helper becomes unnecessary and this test says so.
		"""
		df = frappe.get_meta("Sales Invoice").get_field("is_return")
		self.assertTrue(df.no_copy, "is_return is no longer no_copy — revisit sales_flow.js")

	def test_a_return_takes_the_credit_note_series(self):
		"""The whole point of splitting the entry point: KSCN-, not KSIN-.

		This asserts the HOOK'S OUTPUT, not the configuration. The first version of
		this test only checked the constant and the options string, so it stayed
		green for the entire time the behaviour was broken: the prefix guard in
		``set_naming_series_from_branch`` returned before the ``use_for_return``
		branch ran, because the form pre-fills the branch's own invoice series and
		that starts with the branch prefix.
		"""
		from yht_custom import branch_defaults, setup_branch_series

		self.assertEqual(setup_branch_series.RETURN_SUFFIX_OVERRIDES["Sales Invoice"], "CN")

		company = _first("Company")
		warehouse = frappe.db.get_value(
			"Warehouse", {"company": company, "is_group": 0, "disabled": 0}, "name"
		)
		if not (company and warehouse):
			self.skipTest("site lacks a company or warehouse")

		# This class has no shared fixture — build the branch the hook reads.
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
		cfg.company = company
		cfg.append("warehouse", {"warehouse": warehouse})
		cfg.append("user", {"user": USER, "role": "Branch User"})
		cfg.insert(ignore_permissions=True)
		frappe.clear_cache(user=USER)
		if hasattr(frappe.local, "yht_branch_config_cache"):
			delattr(frappe.local, "yht_branch_config_cache")

		prefix = "ZQ"
		plain, credit = f"{prefix}IN-.YY.-.####", f"{prefix}CN-.YY.-.####"
		branch = frappe.get_doc("Branch", BRANCH)
		if not branch.meta.has_field("custom_naming_series_table"):
			self.skipTest("Branch has no naming series table on this site")
		branch.custom_doc_prefix = prefix
		branch.custom_naming_series_table = []
		for template, use_for_return in ((plain, 0), (credit, 1)):
			branch.append(
				"custom_naming_series_table",
				{
					"parent_doctype": "Sales Invoice",
					"naming_series": template,
					"use_for_return": use_for_return,
				},
			)
		branch.flags.ignore_permissions = True
		branch.save()

		frappe.set_user(USER)
		try:
			# Exactly what the desk hands the hook: the form's pre-filled series,
			# which starts with this branch's prefix.
			ret = frappe.new_doc("Sales Invoice")
			ret.naming_series = plain
			ret.is_return = 1
			branch_defaults.set_naming_series_from_branch(ret)
			self.assertEqual(
				ret.naming_series,
				credit,
				"a return kept the invoice series — the prefix guard fired first",
			)

			# The same guard must still leave a plain invoice alone.
			inv = frappe.new_doc("Sales Invoice")
			inv.naming_series = plain
			inv.is_return = 0
			branch_defaults.set_naming_series_from_branch(inv)
			self.assertEqual(inv.naming_series, plain)

			# And a deliberate in-prefix pick that is not the other flavour's
			# series is still honoured.
			odd = frappe.new_doc("Sales Invoice")
			odd.naming_series = f"{prefix}XX-.YY.-.####"
			odd.is_return = 1
			branch_defaults.set_naming_series_from_branch(odd)
			self.assertEqual(odd.naming_series, f"{prefix}XX-.YY.-.####")
		finally:
			frappe.set_user("Administrator")
			if hasattr(frappe.local, "yht_branch_config_cache"):
				delattr(frappe.local, "yht_branch_config_cache")

	def test_the_helper_is_wired_into_the_js(self):
		"""The dashboard tile and the list button both call one helper."""
		path = frappe.get_app_path("yht_custom", "public", "js", "sales_flow.js")
		src = open(path, encoding="utf-8").read()
		self.assertIn("yht_custom.sales.new_return", src)
		self.assertIn('set_value("is_return", 1)', src)
		# The list button must NOT go through frappe.listview_settings — erpnext
		# reassigns that key wholesale when the list bundle loads, which is after
		# app_include_js, so a merge there is discarded with no error.
		self.assertNotIn("frappe.listview_settings", src)
		self.assertIn('frappe.router.on("change"', src)

	def test_the_dashboard_offers_a_return_tile(self):
		path = frappe.get_app_path(
			"yht_custom", "yht_custom", "page", "yht_dashboard", "yht_dashboard.js"
		)
		src = open(path, encoding="utf-8").read()
		self.assertIn('label: "Sales Return"', src)
		# The tile must be intercepted, not routed — a plain route cannot tick the box.
		self.assertIn("data-yht-return", src)

	def test_the_returns_shortcut_is_a_filtered_list(self):
		"""NOT doc_view New — that would open a blank invoice with the box clear."""
		from yht_custom import workspace_shortcuts

		for workspace, rows in workspace_shortcuts.FILTERED_SHORTCUTS.items():
			for doctype, label, filters in rows:
				with self.subTest(workspace=workspace, label=label):
					self.assertEqual(doctype, "Sales Invoice")
					self.assertEqual(filters, {"is_return": 1})
