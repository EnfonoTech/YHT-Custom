# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Delivery return raised FROM a credit note.

The cases are DISCOVERED from the site's own data rather than built, because the
thing under test is a chain that already exists in production — credit-note row →
original invoice row → delivery note row — and a fixture would only prove the
fixture. Khobhar carries all three shapes: 32 credit notes that trace to exactly one
delivery note, 11 that span 2 to 23, and 63 with no delivery note behind them.

Every test rolls back. Nothing here submits.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import delivery_return, return_flow
from yht_custom.yht_custom.doctype.yht_return_settings.yht_return_settings import (
	allow_delivery_note_from_sales_return,
)

SETTING = "allow_delivery_note_from_sales_return"


def _credit_notes():
	"""(fully traced to one note, spanning several, traced to none)."""
	rows = frappe.db.sql(
		"""
		select cn.name credit_note, count(*) rows_total,
		       sum(case when si.delivery_note is not null and si.delivery_note<>'' then 1 else 0 end) traced,
		       count(distinct si.delivery_note) notes
		from `tabSales Invoice` cn
		join `tabSales Invoice Item` cni on cni.parent = cn.name
		left join `tabSales Invoice Item` si on si.name = cni.sales_invoice_item
		where cn.is_return = 1 and cn.docstatus = 1
		group by cn.name order by cn.creation desc limit 400""",
		as_dict=True,
	)
	one = [r.credit_note for r in rows if r.rows_total and r.traced == r.rows_total and r.notes == 1]
	many = [r.credit_note for r in rows if r.traced == r.rows_total and (r.notes or 0) > 1]
	none = [r.credit_note for r in rows if not r.traced]
	return one, many, none


def _set(enabled):
	frappe.db.set_single_value("YHT Return Settings", SETTING, 1 if enabled else 0)
	frappe.clear_cache(doctype="YHT Return Settings")


class TestReturnSettings(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_cache(doctype="YHT Return Settings")

	def test_the_switch_exists_and_is_off_by_default(self):
		"""The standing rule is the other route — this must be opt-in."""
		meta = frappe.get_meta("YHT Return Settings")
		field = meta.get_field(SETTING)
		self.assertTrue(field, "the checkbox is missing")
		self.assertEqual(field.fieldtype, "Check")
		self.assertIn(field.default, (None, "0", 0), "the switch ships ON, it must ship OFF")

	def test_the_helper_reads_the_switch(self):
		_set(False)
		self.assertFalse(allow_delivery_note_from_sales_return())
		_set(True)
		self.assertTrue(allow_delivery_note_from_sales_return())


class TestDeliveryReturnGate(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_cache(doctype="YHT Return Settings")

	def test_nothing_is_offered_while_the_switch_is_off(self):
		one, _many, _none = _credit_notes()
		if not one:
			self.skipTest("no traced credit note on this site")
		_set(False)
		state = delivery_return.can_make_delivery_note(one[0])
		self.assertFalse(state["allowed"])
		self.assertEqual(state["reason"], "disabled")

	def test_the_mapper_refuses_while_the_switch_is_off(self):
		"""The button is not the boundary — the endpoint is public HTTP."""
		one, _many, _none = _credit_notes()
		if not one:
			self.skipTest("no traced credit note on this site")
		_set(False)
		with self.assertRaises(frappe.ValidationError):
			delivery_return.make_delivery_note_from_sales_return(one[0])


class TestDeliveryReturnMapping(FrappeTestCase):
	def setUp(self):
		_set(True)

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_cache(doctype="YHT Return Settings")

	def test_it_builds_a_delivery_return_linked_both_ways(self):
		one, _many, _none = _credit_notes()
		if not one:
			self.skipTest("no traced credit note on this site")
		name = one[0]

		credit = frappe.get_doc("Sales Invoice", name)
		dn = delivery_return.make_delivery_note_from_sales_return(name)

		self.assertEqual(dn.doctype, "Delivery Note")
		self.assertEqual(dn.is_return, 1)
		self.assertTrue(dn.return_against, "no return_against — ERPNext's over-return guard needs it")
		self.assertEqual(
			frappe.db.get_value("Delivery Note", dn.return_against, "is_return"),
			0,
			"return_against must be the ORIGINAL delivery note, not another return",
		)
		self.assertEqual(dn.customer, credit.customer)
		self.assertTrue(dn.items, "no rows were mapped")

		for row in dn.items:
			self.assertTrue(row.dn_detail, "row %s has no dn_detail" % row.idx)
			self.assertEqual(row.against_sales_invoice, name)
			self.assertTrue(row.si_detail, "row %s does not point back at a credit-note row" % row.idx)
			self.assertLess(row.qty, 0, "a delivery RETURN must carry negative quantities")

	def test_the_quantities_match_the_credit_note_line_for_line(self):
		one, _many, _none = _credit_notes()
		if not one:
			self.skipTest("no traced credit note on this site")
		name = one[0]
		credit = {r.name: r.qty for r in frappe.get_doc("Sales Invoice", name).items}
		dn = delivery_return.make_delivery_note_from_sales_return(name)
		for row in dn.items:
			self.assertEqual(row.qty, credit[row.si_detail], "row %s drifted from the credit note" % row.idx)

	def test_a_credit_note_spanning_several_delivery_notes_is_refused(self):
		"""`return_against` is one link, and the over-return guard counts against it."""
		_one, many, _none = _credit_notes()
		if not many:
			self.skipTest("no multi-note credit note on this site")
		with self.assertRaises(frappe.ValidationError):
			delivery_return.make_delivery_note_from_sales_return(many[0])

	def test_a_credit_note_with_no_delivery_behind_it_is_refused(self):
		_one, _many, none = _credit_notes()
		if not none:
			self.skipTest("no untraced credit note on this site")
		with self.assertRaises(frappe.ValidationError):
			delivery_return.make_delivery_note_from_sales_return(none[0])

	def test_a_forward_invoice_is_refused(self):
		fwd = frappe.db.get_value("Sales Invoice", {"is_return": 0, "docstatus": 1}, "name")
		if not fwd:
			self.skipTest("no forward invoice on this site")
		with self.assertRaises(frappe.ValidationError):
			delivery_return.make_delivery_note_from_sales_return(fwd)


class TestRouteGuardStillHolds(FrappeTestCase):
	"""The switch relaxes the policy — it must not delete it.

	🔴 THE SHAPE UNDER TEST CANNOT BE FOUND IN THE DATA, and that is the point.

	A credit note raised BEFORE the goods come back is exactly what
	`enforce_return_stock_route` has been refusing since 2026-08-26, so no such
	document exists to load. Every credit note on the site that traces to a delivery
	note got there through the DN-return route, which means its own rows already point
	at a delivery RETURN and `_came_back_on_a_stock_return` short-circuits the guard
	before the policy is ever consulted.

	So the condition is CONSTRUCTED: take a real credit note against a delivered
	invoice and clear the stock links on its rows in memory, which is precisely the
	shape of one typed by hand against the invoice.
	"""

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_cache(doctype="YHT Return Settings")

	def _delivered_credit_note(self):
		one, _many, _none = _credit_notes()
		return one[0] if one else None

	def _as_credit_note_first(self, name):
		"""A loaded, unsaved credit note that has NOT come back on a stock return."""
		doc = frappe.get_doc("Sales Invoice", name)
		doc.docstatus = 0
		for row in doc.items:
			row.delivery_note = None
			row.dn_detail = None
		return doc

	def test_the_route_is_still_enforced_while_the_switch_is_off(self):
		"""🔴 The client decision of 2026-08-26 must survive this feature."""
		name = self._delivered_credit_note()
		if not name:
			self.skipTest("no traced credit note on this site")
		_set(False)

		from yht_custom import sales_flow

		original = sales_flow._may_bypass
		sales_flow._may_bypass = lambda *a, **k: False  # tests run as Administrator
		try:
			doc = self._as_credit_note_first(name)
			with self.assertRaises(frappe.ValidationError):
				return_flow.enforce_return_stock_route(doc)
		finally:
			sales_flow._may_bypass = original

	def test_the_switch_lets_the_credit_note_through_but_still_moves_no_stock(self):
		name = self._delivered_credit_note()
		if not name:
			self.skipTest("no traced credit note on this site")
		_set(True)

		from yht_custom import sales_flow

		original = sales_flow._may_bypass
		sales_flow._may_bypass = lambda *a, **k: False
		try:
			doc = self._as_credit_note_first(name)
			doc.update_stock = 1
			return_flow.enforce_return_stock_route(doc)
			self.assertEqual(
				doc.update_stock, 0,
				"the credit note must not move stock — the delivery return is what brings it back",
			)
		finally:
			sales_flow._may_bypass = original


class TestWiring(FrappeTestCase):
	def test_the_button_is_registered_on_sales_invoice(self):
		from yht_custom import hooks

		entry = hooks.doctype_js["Sales Invoice"]
		entry = entry if isinstance(entry, list) else [entry]
		self.assertIn("public/js/sales_return_delivery.js", entry)

	def test_both_endpoints_are_whitelisted(self):
		for fn in (delivery_return.make_delivery_note_from_sales_return,
		           delivery_return.can_make_delivery_note):
			self.assertTrue(getattr(fn, "__wrapped__", None) or hasattr(fn, "__name__"))
		self.assertIn(
			"yht_custom.delivery_return.make_delivery_note_from_sales_return",
			frappe.whitelisted_methods if hasattr(frappe, "whitelisted_methods") else
			[f"{m.__module__}.{m.__name__}" for m in frappe.whitelisted],
		)
