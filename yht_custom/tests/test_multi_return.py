# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""The multi-delivery-note return screen.

The one invariant worth guarding: it creates ONE return per source note. A merged
return SAVES and SUBMITS with only the first note in `return_against`, silently
never crediting the second — that is the bug this screen exists to make
unreachable, so a test that lets it back in is worse than no test.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from yht_custom import multi_return


def _template():
	return frappe.db.sql(
		"""SELECT dn.customer, dn.company, dni.item_code, dni.warehouse, dni.rate, dni.cost_center
		   FROM `tabDelivery Note` dn JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		   WHERE dn.docstatus = 1 AND dn.is_return = 0
		   ORDER BY dn.creation DESC LIMIT 1""",
		as_dict=True,
	)


class TestMultiReturn(FrappeTestCase):
	def setUp(self):
		rows = _template()
		if not rows:
			self.skipTest("no submitted delivery note on this site to model")
		self.tmpl = rows[0]

	def tearDown(self):
		frappe.db.rollback()

	def _note(self, qty=10):
		doc = frappe.new_doc("Delivery Note")
		doc.customer, doc.company = self.tmpl.customer, self.tmpl.company
		doc.append(
			"items",
			{
				"item_code": self.tmpl.item_code,
				"qty": qty,
				"rate": self.tmpl.rate,
				"warehouse": self.tmpl.warehouse,
				"cost_center": self.tmpl.cost_center,
			},
		)
		doc.save()
		doc.submit()
		return doc

	def _find(self, notes, name):
		return next((n for n in notes if n["name"] == name), None)

	# ------------------------------------------------------------------ listing

	def test_a_fresh_note_is_fully_returnable(self):
		dn = self._note(10)
		found = self._find(multi_return.returnable_delivery_notes(self.tmpl.customer), dn.name)
		self.assertIsNotNone(found)
		self.assertEqual(len(found["items"]), 1)
		self.assertEqual(flt(found["items"][0]["returnable"]), 10)
		self.assertEqual(flt(found["items"][0]["returned"]), 0)

	def test_a_partly_returned_note_offers_only_the_remainder(self):
		dn = self._note(10)
		multi_return.create_returns(
			self.tmpl.customer,
			json.dumps([{"delivery_note": dn.name, "rows": [{"row_name": dn.items[0].name, "qty": 4}]}]),
			submit=1,
		)
		found = self._find(multi_return.returnable_delivery_notes(self.tmpl.customer), dn.name)
		self.assertEqual(flt(found["items"][0]["returned"]), 4)
		self.assertEqual(flt(found["items"][0]["returnable"]), 6)

	def test_a_fully_returned_note_disappears(self):
		"""⚠️ NOT driven by per_returned — that is maintained by the status updater
		and was observed sitting at 0 after three partial returns. The row remainder
		is the authority, so the note has to drop out on the row maths alone."""
		dn = self._note(10)
		multi_return.create_returns(
			self.tmpl.customer,
			json.dumps([{"delivery_note": dn.name, "rows": [{"row_name": dn.items[0].name, "qty": 10}]}]),
			submit=1,
		)
		self.assertIsNone(self._find(multi_return.returnable_delivery_notes(self.tmpl.customer), dn.name))

	def test_a_draft_note_is_never_offered(self):
		doc = frappe.new_doc("Delivery Note")
		doc.customer, doc.company = self.tmpl.customer, self.tmpl.company
		doc.append(
			"items",
			{
				"item_code": self.tmpl.item_code,
				"qty": 5,
				"rate": self.tmpl.rate,
				"warehouse": self.tmpl.warehouse,
				"cost_center": self.tmpl.cost_center,
			},
		)
		doc.save()
		self.assertIsNone(self._find(multi_return.returnable_delivery_notes(self.tmpl.customer), doc.name))

	def test_no_customer_returns_nothing(self):
		self.assertEqual(multi_return.returnable_delivery_notes(""), [])

	# ------------------------------------------------------------------ creating

	def test_two_notes_produce_TWO_returns_not_one_merged(self):
		"""🔴 The whole point. A merged return links only its first source."""
		a, b = self._note(5), self._note(5)
		result = multi_return.create_returns(
			self.tmpl.customer,
			json.dumps(
				[
					{"delivery_note": a.name, "rows": [{"row_name": a.items[0].name, "qty": 5}]},
					{"delivery_note": b.name, "rows": [{"row_name": b.items[0].name, "qty": 5}]},
				]
			),
			submit=1,
		)
		self.assertEqual(result["failed"], [])
		self.assertEqual(len(result["created"]), 2)
		against = {
			frappe.db.get_value("Delivery Note", r["return"], "return_against")
			for r in result["created"]
		}
		self.assertEqual(against, {a.name, b.name}, "each return must name its own source")

	def test_an_unticked_row_is_removed_not_zeroed(self):
		"""A zero-qty row fails validation; a full-qty one returns goods they kept."""
		dn = frappe.new_doc("Delivery Note")
		dn.customer, dn.company = self.tmpl.customer, self.tmpl.company
		for _i in range(2):
			dn.append(
				"items",
				{
					"item_code": self.tmpl.item_code,
					"qty": 3,
					"rate": self.tmpl.rate,
					"warehouse": self.tmpl.warehouse,
					"cost_center": self.tmpl.cost_center,
				},
			)
		dn.save()
		dn.submit()

		result = multi_return.create_returns(
			self.tmpl.customer,
			json.dumps(
				[{"delivery_note": dn.name, "rows": [{"row_name": dn.items[0].name, "qty": 3}]}]
			),
			submit=1,
		)
		self.assertEqual(result["failed"], [])
		created = frappe.get_doc("Delivery Note", result["created"][0]["return"])
		self.assertEqual(len(created.items), 1)
		self.assertEqual(created.items[0].dn_detail, dn.items[0].name)

	def test_quantities_come_back_negative(self):
		dn = self._note(6)
		result = multi_return.create_returns(
			self.tmpl.customer,
			json.dumps([{"delivery_note": dn.name, "rows": [{"row_name": dn.items[0].name, "qty": 6}]}]),
		)
		created = frappe.get_doc("Delivery Note", result["created"][0]["return"])
		self.assertEqual(flt(created.items[0].qty), -6)
		self.assertEqual(created.is_return, 1)

	def test_a_credit_note_is_raised_and_linked(self):
		dn = self._note(4)
		from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice

		# bill it first, so the credit note has an invoice to settle
		si = make_sales_invoice(dn.name)
		si.save()
		si.submit()

		result = multi_return.create_returns(
			self.tmpl.customer,
			json.dumps([{"delivery_note": dn.name, "rows": [{"row_name": dn.items[0].name, "qty": 4}]}]),
			submit=1,
			raise_credit_notes=1,
		)
		self.assertEqual(result["failed"], [])
		made = result["created"][0]
		self.assertTrue(made["credit_note"])
		self.assertEqual(made["settles"], si.name)

	def test_a_credit_note_without_submit_is_refused(self):
		dn = self._note(2)
		with self.assertRaises(frappe.ValidationError):
			multi_return.create_returns(
				self.tmpl.customer,
				json.dumps([{"delivery_note": dn.name, "rows": [{"row_name": dn.items[0].name, "qty": 2}]}]),
				submit=0,
				raise_credit_notes=1,
			)

	def test_a_note_belonging_to_another_customer_is_refused(self):
		dn = self._note(3)
		other = frappe.db.get_value("Customer", {"name": ["!=", self.tmpl.customer]}, "name")
		if not other:
			self.skipTest("only one customer on this site")
		result = multi_return.create_returns(
			other,
			json.dumps([{"delivery_note": dn.name, "rows": [{"row_name": dn.items[0].name, "qty": 3}]}]),
		)
		self.assertEqual(result["created"], [])
		self.assertEqual(len(result["failed"]), 1)
		self.assertIn("does not belong", result["failed"][0]["error"])

	def test_one_bad_note_does_not_discard_the_good_one(self):
		"""Each note runs in its own SAVEPOINT, so the batch is not all-or-nothing."""
		good = self._note(5)
		result = multi_return.create_returns(
			self.tmpl.customer,
			json.dumps(
				[
					{"delivery_note": good.name, "rows": [{"row_name": good.items[0].name, "qty": 5}]},
					{"delivery_note": good.name, "rows": [{"row_name": good.items[0].name, "qty": 999}]},
				]
			),
			submit=1,
		)
		self.assertEqual(len(result["created"]), 1)
		self.assertEqual(len(result["failed"]), 1)
		self.assertTrue(frappe.db.exists("Delivery Note", result["created"][0]["return"]))

	def test_an_over_return_is_refused_by_erpnexts_own_guard(self):
		dn = self._note(2)
		result = multi_return.create_returns(
			self.tmpl.customer,
			json.dumps([{"delivery_note": dn.name, "rows": [{"row_name": dn.items[0].name, "qty": 50}]}]),
			submit=1,
		)
		self.assertEqual(result["created"], [])
		self.assertEqual(len(result["failed"]), 1)

	def test_an_empty_selection_creates_nothing(self):
		result = multi_return.create_returns(self.tmpl.customer, json.dumps([]))
		self.assertEqual(result, {"created": [], "failed": []})


class TestMultiReturnWiring(FrappeTestCase):
	def test_the_page_exists_and_is_role_gated(self):
		page = frappe.get_doc("Page", "yht-multi-return")
		roles = {r.role for r in page.roles}
		self.assertIn("Branch User", roles)
		self.assertTrue(roles, "an ungated page is visible to every logged-in user")

	def test_the_route_is_allowed_for_a_branch_user(self):
		"""🔴 Absent from ALLOWED_ROUTES, a lone slug is treated as a doctype the
		role cannot open and the branch user is bounced to the dashboard."""
		import pathlib

		source = pathlib.Path(frappe.get_app_path("yht_custom", "public", "js", "branch_user_restrict.js"))
		self.assertIn('"yht-multi-return"', source.read_text())

	def test_the_dashboard_tile_points_at_the_page(self):
		import pathlib

		source = pathlib.Path(
			frappe.get_app_path("yht_custom", "yht_custom", "page", "yht_dashboard", "yht_dashboard.js")
		)
		self.assertIn('page: "yht-multi-return"', source.read_text())

	def test_both_endpoints_are_whitelisted(self):
		for path in (
			"yht_custom.multi_return.returnable_delivery_notes",
			"yht_custom.multi_return.create_returns",
		):
			with self.subTest(path=path):
				# ⚠️ keyed by the FUNCTION OBJECT, not the dotted path
				self.assertIn(frappe.get_attr(path), frappe.whitelisted)


class TestMultiReturnCreditNotes(FrappeTestCase):
	"""🔴 Crediting an UNINVOICED delivery note hands out free money.

	Reproduced before the guard existed: KSDN-26-0541 had per_billed 0, the screen
	still raised credit note KSIN-26-0614 for -13.80, and its receivable GL posted
	Cr 14.00 against a customer who had never been charged for those goods.
	"""

	def setUp(self):
		rows = _template()
		if not rows:
			self.skipTest("no submitted delivery note on this site to model")
		self.tmpl = rows[0]

	def tearDown(self):
		frappe.db.rollback()

	def _note(self, qty=4):
		doc = frappe.new_doc("Delivery Note")
		doc.customer, doc.company = self.tmpl.customer, self.tmpl.company
		doc.append(
			"items",
			{
				"item_code": self.tmpl.item_code,
				"qty": qty,
				"rate": self.tmpl.rate,
				"warehouse": self.tmpl.warehouse,
				"cost_center": self.tmpl.cost_center,
			},
		)
		doc.save()
		doc.submit()
		return doc

	def _return_all(self, dn, **kw):
		return multi_return.create_returns(
			self.tmpl.customer,
			json.dumps([{"delivery_note": dn.name, "rows": [{"row_name": dn.items[0].name, "qty": dn.items[0].qty}]}]),
			**kw,
		)

	def test_an_uninvoiced_note_gets_a_return_but_NO_credit_note(self):
		dn = self._note()
		self.assertEqual(multi_return._invoices_billing(dn.name), [])

		result = self._return_all(dn, submit=1, raise_credit_notes=1)
		self.assertEqual(result["failed"], [])
		made = result["created"][0]

		self.assertTrue(made["return"], "the goods must still come back")
		self.assertIsNone(made["credit_note"], "nothing was invoiced, so nothing to credit")
		self.assertIn("never invoiced", made["credit_skipped"])

	def test_the_skip_is_reported_not_silent(self):
		"""Saying nothing is how a clerk assumes the credit note happened."""
		dn = self._note()
		made = self._return_all(dn, submit=1, raise_credit_notes=1)["created"][0]
		self.assertTrue(made.get("credit_skipped"))
		self.assertIn(dn.name, made["credit_skipped"])

	def test_an_invoiced_note_still_gets_a_credit_note_that_settles(self):
		from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice

		dn = self._note()
		si = make_sales_invoice(dn.name)
		si.save()
		si.submit()
		self.assertEqual(multi_return._invoices_billing(dn.name), [si.name])

		made = self._return_all(dn, submit=1, raise_credit_notes=1)["created"][0]
		self.assertTrue(made["credit_note"])
		self.assertEqual(made["settles"], si.name)
		self.assertIsNone(made.get("credit_skipped"))

		after = frappe.db.get_value("Sales Invoice", si.name, ["status", "outstanding_amount"], as_dict=True)
		self.assertEqual(flt(after.outstanding_amount), 0.0)
		self.assertEqual(after.status, "Credit Note Issued")

	def test_billing_evidence_is_direct_not_per_billed(self):
		"""⚠️ `per_billed` is status-updater maintained and can lag.

		Its sibling `per_returned` was observed at 0 after three submitted partial
		returns. A percentage that can lag must not gate an accounting entry.
		"""
		import inspect

		import ast
		import textwrap

		# Drop the DOCSTRING and keep the code. Splitting on triple quotes does not
		# work here: the function holds a triple-quoted SQL string too, so a naive
		# split hands back the tail after the query instead of the body.
		tree = ast.parse(textwrap.dedent(inspect.getsource(multi_return._invoices_billing)))
		fn = tree.body[0]
		if ast.get_docstring(fn):
			fn.body = fn.body[1:]
		body = ast.unparse(fn)

		self.assertIn("tabSales Invoice Item", body)
		self.assertNotIn("per_billed", body)
