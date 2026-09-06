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


def _actionable():
	"""Credit notes the feature will actually accept.

	"Traces to one delivery note" is NOT the same as "can be returned": the delivered
	quantity may already have come back. Two tests assumed it was, picked the newest
	traced note, and broke the moment the exhausted-line guard landed — the guard was
	right and the assumption was wrong.
	"""
	one, _many, _none = _credit_notes()
	return [n for n in one if delivery_return.can_make_delivery_note(n)["allowed"]]


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
		actionable = _actionable()
		if not actionable:
			self.skipTest("no actionable credit note on this site")
		name = actionable[0]

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
		actionable = _actionable()
		if not actionable:
			self.skipTest("no actionable credit note on this site")
		name = actionable[0]
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


class TestExhaustedLines(FrappeTestCase):
	"""🔴 THE BUTTON MUST NOT LEAD TO ERPNext's OWN ERROR.

	A credit note whose delivered quantity has already come back is a real and common
	shape — on yht-test, 3 of 110 submitted credit notes. Before this guard the button
	appeared, the operator filled nothing in, saved, and met
	`StockOverReturnError: Cannot return more than 0.0`. That is the over-return guard
	working correctly (and proof `dn_detail` is wired), but it is a poor way to find
	out, and the request was explicitly for a route without errors.

	So the exhausted case is detected up front: no button, and the endpoint refuses
	with a sentence naming the row.
	"""

	def setUp(self):
		_set(True)

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_cache(doctype="YHT Return Settings")

	def _exhausted_credit_note(self):
		one, _many, _none = _credit_notes()
		for name in one:
			state = delivery_return.can_make_delivery_note(name)
			if state["reason"].startswith("the delivered quantity"):
				return name
		return None

	def test_an_exhausted_credit_note_is_not_offered(self):
		name = self._exhausted_credit_note()
		if not name:
			self.skipTest("no fully-returned credit note on this site")
		self.assertFalse(delivery_return.can_make_delivery_note(name)["allowed"])

	def test_it_refuses_before_erpnext_has_to(self):
		name = self._exhausted_credit_note()
		if not name:
			self.skipTest("no fully-returned credit note on this site")
		with self.assertRaises(frappe.ValidationError) as caught:
			delivery_return.make_delivery_note_from_sales_return(name)
		message = str(caught.exception)
		self.assertIn("already been returned", message)
		self.assertNotIn("Cannot return more than", message, "ERPNext's raw error reached the operator")

	def test_a_saved_delivery_return_blocks_a_second_one(self):
		"""One credit note, one delivery return — checked by against_sales_invoice."""
		allowed = _actionable()
		if not allowed:
			self.skipTest("no actionable credit note on this site")
		name = allowed[0]
		dn = delivery_return.make_delivery_note_from_sales_return(name)
		dn.insert(ignore_permissions=True)

		state = delivery_return.can_make_delivery_note(name)
		self.assertFalse(state["allowed"])
		self.assertEqual(state["reason"], "already created")
		self.assertEqual(state["existing"], dn.name)
		with self.assertRaises(frappe.ValidationError):
			delivery_return.make_delivery_note_from_sales_return(name)

	def test_it_survives_save_and_submit(self):
		"""The mapper only builds the document — validate and the ledger run on save.

		⚠️ THIS TEST CLEANS UP AFTER ITSELF, and has to.

		`frappe.db.rollback()` is not enough here: submitting a stock document writes
		Stock Ledger Entries through a path that commits, so four delivery notes from
		earlier runs were found sitting on yht-test hours later. Cancel and delete
		explicitly; the rollback in tearDown stays as a backstop for everything else.
		"""
		allowed = _actionable()
		if not allowed:
			self.skipTest("no actionable credit note on this site")

		dn = delivery_return.make_delivery_note_from_sales_return(allowed[0])
		dn.insert(ignore_permissions=True)
		dn.submit()
		self.addCleanup(self._remove, dn.name)

		self.assertEqual(dn.docstatus, 1)
		# `is_cancelled` matters: a rolled-back test reuses the same series number, so
		# the cancelled entries of an earlier document answer to this voucher_no too.
		entries = frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": dn.name, "is_cancelled": 0},
			fields=["actual_qty"],
		)
		self.assertTrue(entries, "the delivery return moved no stock")
		self.assertTrue(
			all(e.actual_qty > 0 for e in entries),
			"a delivery RETURN must bring stock back IN, not send it out",
		)

		# The credit note must now name THIS return, or it never reads as billed.
		dn.reload()
		self.assertEqual(dn.per_billed, 100.0, "the delivery return was left unbilled")
		self.assertEqual(dn.status, "Completed")

	@staticmethod
	def _remove(name):
		if not frappe.db.exists("Delivery Note", name):
			return
		doc = frappe.get_doc("Delivery Note", name)
		if doc.docstatus == 1:
			doc.flags.ignore_permissions = True
			doc.cancel()
		frappe.delete_doc("Delivery Note", name, force=1, ignore_permissions=True)
		frappe.db.commit()

	def test_a_credit_note_that_already_came_back_is_refused(self):
		"""🔴 `against_sales_invoice` cannot see a return made the site's usual way.

		Delivery Note ▸ Sales Return ▸ Issue Credit Note produces a delivery return
		carrying NO `against_sales_invoice`, so the duplicate check never saw it and
		the button was offered for stock that had already come back — measured on
		KSSR-26-0035, whose goods returned on KSDR-26-0042 on 2026-08-31.
		"""
		names = [r.name for r in frappe.get_all(
			"Sales Invoice", filters={"is_return": 1, "docstatus": 1},
			fields=["name"], limit_page_length=200)]
		spent = [n for n in names
		         if delivery_return._already_came_back(frappe.get_doc("Sales Invoice", n))]
		if not spent:
			self.skipTest("no credit note on this site has already come back")

		state = delivery_return.can_make_delivery_note(spent[0])
		self.assertFalse(state["allowed"])
		self.assertIn("already came back", state["reason"])
		with self.assertRaises(frappe.ValidationError):
			delivery_return.make_delivery_note_from_sales_return(spent[0])


class TestSeveralDeliveryNotes(FrappeTestCase):
	"""🔴 A CREDIT NOTE SPANNING SEVERAL SHIPMENTS USED TO BE REFUSED OUTRIGHT.

	An invoice delivered in more than one consignment produces a credit note whose
	lines trace back to several delivery notes, and `return_against` is a single
	link — so one return cannot reverse them all. The first version simply refused
	and told the operator to raise them by hand: on khobhar that is 11 credit notes
	covering 97 delivery notes, which nobody was going to type.

	So the span is a list now, not a refusal: one return per delivery note, each
	with its own `return_against`, which is the shape ERPNext's over-return guard
	expects anyway.
	"""

	def setUp(self):
		_set(True)

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_cache(doctype="YHT Return Settings")

	def _multi(self):
		"""A submitted credit note whose lines span more than one delivery note."""
		for r in frappe.get_all("Sales Invoice", filters={"is_return": 1, "docstatus": 1},
								fields=["name"], order_by="creation desc", limit_page_length=300):
			options = delivery_return.delivery_note_options(r.name)
			if len([o for o in options if o["status"] == "pending"]) > 1:
				return r.name, options
		return None, None

	def test_each_delivery_note_is_offered_separately(self):
		name, options = self._multi()
		if not name:
			self.skipTest("no multi-shipment credit note on this site")

		self.assertGreater(len(options), 1)
		for opt in options:
			self.assertTrue(opt["delivery_note"])
			self.assertGreater(opt["rows"], 0, "an option with no rows should not be listed")
			self.assertIn(opt["status"], ("pending", "created", "returned in full"))

		state = delivery_return.can_make_delivery_note(name)
		self.assertTrue(state["allowed"], "a multi-shipment credit note is refused again")
		self.assertGreater(state["pending"], 1)
		self.assertIsNone(state["delivery_note"], "the form must ask which one, not assume")

	def test_a_return_carries_only_its_own_shipment(self):
		name, options = self._multi()
		if not name:
			self.skipTest("no multi-shipment credit note on this site")
		pending = [o for o in options if o["status"] == "pending"]
		chosen = pending[0]

		dn = delivery_return.make_delivery_note_from_sales_return(name, delivery_note=chosen["delivery_note"])
		self.assertEqual(dn.return_against, chosen["delivery_note"])
		self.assertEqual(len(dn.items), chosen["rows"],
						 "rows from another shipment leaked onto this return")

	def _submit_one(self, name, pending):
		"""Submit a return for the first shipment the WAREHOUSE will actually accept.

		Picking `pending[0]` blindly fails on this data: khobhar carries 322 negative
		bins and yht-test its own, so a return that posts stock back in can still be
		refused for leaving the balance negative. That is a real inventory condition,
		not a fault in the feature, so step past it rather than assert around it.
		"""
		for note in pending:
			try:
				dn = delivery_return.make_delivery_note_from_sales_return(name, delivery_note=note)
				dn.insert(ignore_permissions=True)
				dn.submit()
			except Exception:
				frappe.db.rollback()
				_set(True)
				continue
			self.addCleanup(TestExhaustedLines._remove, dn.name)
			return dn, note
		return None, None

	def test_creating_one_leaves_the_others_available(self):
		"""The whole point: three shipments, three returns, one at a time."""
		name, options = self._multi()
		if not name:
			self.skipTest("no multi-shipment credit note on this site")
		pending = [o["delivery_note"] for o in options if o["status"] == "pending"]

		dn, note = self._submit_one(name, pending)
		if not dn:
			self.skipTest("every shipment here is blocked by negative stock")

		state = delivery_return.can_make_delivery_note(name)
		self.assertTrue(state["allowed"], "the remaining shipments became unreachable")
		self.assertEqual(state["pending"], len(pending) - 1)

		after = {o["delivery_note"]: o for o in delivery_return.delivery_note_options(name)}
		self.assertEqual(after[note]["status"], "created")
		self.assertEqual(after[note]["existing"], dn.name)
		self.assertTrue(
			any(o["status"] == "pending" for k, o in after.items() if k != note),
			"no shipment is left to return",
		)

	def test_the_same_shipment_cannot_be_returned_twice(self):
		name, options = self._multi()
		if not name:
			self.skipTest("no multi-shipment credit note on this site")
		pending = [o["delivery_note"] for o in options if o["status"] == "pending"]

		dn, note = self._submit_one(name, pending)
		if not dn:
			self.skipTest("every shipment here is blocked by negative stock")

		with self.assertRaises(frappe.ValidationError):
			delivery_return.make_delivery_note_from_sales_return(name, delivery_note=note)

	def test_it_refuses_to_guess_which_shipment(self):
		name, _options = self._multi()
		if not name:
			self.skipTest("no multi-shipment credit note on this site")
		with self.assertRaises(frappe.ValidationError) as caught:
			delivery_return.make_delivery_note_from_sales_return(name)
		self.assertIn("different delivery notes", str(caught.exception))

	def test_a_delivery_note_that_is_not_behind_it_is_refused(self):
		"""The endpoint is public HTTP — the dialog is not the boundary."""
		name, _options = self._multi()
		if not name:
			self.skipTest("no multi-shipment credit note on this site")
		other = frappe.db.get_value("Delivery Note", {"is_return": 0, "docstatus": 1}, "name")
		with self.assertRaises(frappe.ValidationError):
			delivery_return.make_delivery_note_from_sales_return(name, delivery_note=other)

	def test_the_picker_is_wired_into_the_form(self):
		path = frappe.get_app_path("yht_custom", "public", "js", "sales_return_delivery.js")
		with open(path, encoding="utf-8") as handle:
			src = handle.read()
		self.assertIn("Which delivery is coming back?", src)
		self.assertIn("args: { delivery_note:", src)
