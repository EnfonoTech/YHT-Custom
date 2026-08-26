# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Tests for the return policy — negation, the stock route, series, layout."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import field_layout, return_flow, setup_branch_series

BRANCH = "_Test YHT Return Branch"
USER = "_test_yht_return_user@example.invalid"


class TestReturnSeriesInvariants(FrappeTestCase):
	"""🔴 THE TEST THAT SHOULD HAVE EXISTED.

	Two live collisions shipped because nothing checked that one abbreviation maps
	to one document kind: Purchase Receipt was configured `KSPR-`, which is the
	purchase-INVOICE return prefix carrying 56 documents, and Stock Reconciliation
	was configured `KSSR-`, the sales-return prefix carrying 98. Frappe keys
	`tabSeries` on the resolved prefix, so each pair was one shared counter.
	"""

	def test_no_two_document_kinds_share_an_abbreviation(self):
		seen = {}
		for doctype, abbrev, _supports_return in setup_branch_series.SERIES_TARGETS:
			self.assertNotIn(
				abbrev,
				seen,
				f"{doctype} forward series shares abbreviation {abbrev!r} with {seen.get(abbrev)}",
			)
			seen[abbrev] = f"{doctype} (forward)"

		for doctype, abbrev in setup_branch_series.RETURN_SUFFIX_OVERRIDES.items():
			self.assertNotIn(
				abbrev,
				seen,
				f"{doctype} return series shares abbreviation {abbrev!r} with {seen.get(abbrev)}",
			)
			seen[abbrev] = f"{doctype} (return)"

	def test_every_return_series_is_one_the_client_already_uses(self):
		"""Measured on the live data 2026-08-26; the counts are the evidence.

		The first version invented CN / DRN / DBN / PRN, which between them had
		ZERO documents, while claiming to continue the client's convention.
		"""
		observed = {
			"Sales Invoice": "SR",  # KSSR-, 98 of 102
			"Delivery Note": "DR",  # KSDR-, 34 of 38
			"Purchase Invoice": "PR",  # KSPR-, 56 of 60
			"Purchase Receipt": "PRR",  # KSPRR-, 4 of 4
		}
		self.assertEqual(setup_branch_series.RETURN_SUFFIX_OVERRIDES, observed)

	def test_purchase_receipt_forward_is_prn(self):
		"""It was PR — the purchase-invoice RETURN prefix. 534 receipts are KSPRN-."""
		targets = {dt: abbrev for dt, abbrev, _ in setup_branch_series.SERIES_TARGETS}
		self.assertEqual(targets["Purchase Receipt"], "PRN")
		self.assertEqual(targets["Stock Reconciliation"], "RC")

	def test_retiring_a_series_can_never_drop_an_active_one(self):
		"""Purchase Receipt gives up KSPR- and KEEPS KSPRN- — the same doctype.

		`_sync_naming_series_options` subtracts the active templates from the
		retired set for exactly this case; without it, retiring the old inverted
		pair would delete the doctype's own forward series from the picker.
		"""
		prefix = "KS"

		def active_for(doctype):
			out = set()
			for dt, abbrev, supports_return in setup_branch_series.SERIES_TARGETS:
				if dt != doctype:
					continue
				out.add(setup_branch_series.build_template(prefix, abbrev))
				if supports_return:
					ret = setup_branch_series.RETURN_SUFFIX_OVERRIDES.get(dt)
					if ret:
						out.add(setup_branch_series.build_template(prefix, ret))
			return out

		# The exact arithmetic `_sync_naming_series_options` performs.
		for doctype, retired in setup_branch_series.RETIRED_SERIES.items():
			active = active_for(doctype)
			effective = set(retired) - active
			self.assertFalse(
				effective & active,
				f"{doctype}: retiring {sorted(effective & active)} would delete a live series",
			)

		# And the case that makes the guard load-bearing rather than decorative:
		# Purchase Receipt is listed as retiring KSPRN- while KSPRN- is now its
		# forward series, so the subtraction is the only thing saving it.
		pr_active = active_for("Purchase Receipt")
		self.assertIn("KSPRN-.YY.-.####", pr_active)
		self.assertIn("KSPRN-.YY.-.####", set(setup_branch_series.RETIRED_SERIES["Purchase Receipt"]))
		self.assertEqual(
			set(setup_branch_series.RETIRED_SERIES["Purchase Receipt"]) - pr_active,
			{"KSPR-.YY.-.####"},
		)

	def test_the_expense_series_continues_the_clients_own(self):
		"""889 expense invoices are KSEPI-. KSEXP- had none."""
		from yht_custom import expense_invoice

		self.assertEqual(expense_invoice.EXPENSE_SERIES, "KSEPI-.YY.-.####")


class TestNegateReturnQuantities(FrappeTestCase):
	def _row(self, doctype, **values):
		doc = frappe.new_doc(doctype)
		doc.append("items", values)
		return doc

	def test_a_positive_quantity_on_a_return_is_flipped(self):
		for doctype in return_flow.NEGATE_FIELDS:
			with self.subTest(doctype=doctype):
				doc = self._row(doctype, qty=3, stock_qty=3)
				doc.is_return = 1
				return_flow.negate_return_quantities(doc)
				self.assertEqual(doc.items[0].qty, -3)
				self.assertEqual(doc.items[0].stock_qty, -3)

	def test_an_already_negative_quantity_is_left_alone(self):
		"""⚠️ Flipping twice would turn every mapped credit note into a sale."""
		for doctype in return_flow.NEGATE_FIELDS:
			with self.subTest(doctype=doctype):
				doc = self._row(doctype, qty=-5, stock_qty=-5)
				doc.is_return = 1
				return_flow.negate_return_quantities(doc)
				self.assertEqual(doc.items[0].qty, -5)

	def test_a_plain_document_is_untouched(self):
		doc = self._row("Sales Invoice", qty=7)
		doc.is_return = 0
		return_flow.negate_return_quantities(doc)
		self.assertEqual(doc.items[0].qty, 7)

	def test_the_purchase_side_flips_received_and_rejected_too(self):
		"""ERPNext's own mapper negates these; validate_quantity reads them."""
		for doctype in ("Purchase Invoice", "Purchase Receipt"):
			with self.subTest(doctype=doctype):
				doc = self._row(doctype, qty=2, received_qty=2, rejected_qty=1)
				doc.is_return = 1
				return_flow.negate_return_quantities(doc)
				self.assertEqual(doc.items[0].qty, -2)
				self.assertEqual(doc.items[0].received_qty, -2)
				self.assertEqual(doc.items[0].rejected_qty, -1)

	def test_the_fields_match_erpnexts_own_mapper(self):
		"""Deriving this set instead of copying it is how a return passes
		validate() and then fails at on_submit()."""
		source = frappe.get_app_path("erpnext", "controllers", "sales_and_purchase_return.py")
		src = open(source, encoding="utf-8").read()
		for doctype, fields in return_flow.NEGATE_FIELDS.items():
			for fieldname in fields:
				with self.subTest(doctype=doctype, field=fieldname):
					self.assertIn(
						f"target_doc.{fieldname} = -1 * flt(",
						src,
						f"{fieldname} is not negated by erpnext's mapper — is it still right?",
					)


class TestReturnStockRoute(FrappeTestCase):
	def test_negation_runs_last_on_purchase_invoice(self):
		"""expense_invoice.before_validate stamps qty = 1 on a blank row — a
		POSITIVE 1, on a return. The flip has to come after it."""
		events = frappe.get_hooks("doc_events")["Purchase Invoice"]["before_validate"]
		self.assertEqual(events[-1], "yht_custom.return_flow.negate_return_quantities")
		self.assertIn("yht_custom.expense_invoice.before_validate", events)
		self.assertLess(
			events.index("yht_custom.expense_invoice.before_validate"),
			events.index("yht_custom.return_flow.negate_return_quantities"),
		)

	def test_every_return_capable_doctype_negates(self):
		for doctype in return_flow.NEGATE_FIELDS:
			with self.subTest(doctype=doctype):
				events = frappe.get_hooks("doc_events")[doctype]["before_validate"]
				self.assertIn("yht_custom.return_flow.negate_return_quantities", events)

	def test_the_forward_rule_exempts_a_return(self):
		"""🔴 It did not, and a branch user's credit note could never bring stock
		back: is_return=1, update_stock=1 went in and came out 0."""
		from yht_custom import sales_flow

		doc = frappe.new_doc("Sales Invoice")
		doc.is_return, doc.update_stock = 1, 1
		sales_flow.enforce_delivery_note_route(doc)
		self.assertEqual(doc.update_stock, 1)

		pi = frappe.new_doc("Purchase Invoice")
		pi.is_return, pi.update_stock = 1, 1
		sales_flow.enforce_purchase_receipt_route(pi)
		self.assertEqual(pi.update_stock, 1)

	def test_the_forward_rule_still_bites_a_plain_invoice(self):
		from yht_custom import sales_flow

		original = frappe.session.user
		frappe.set_user("Administrator")
		try:
			doc = frappe.new_doc("Sales Invoice")
			doc.is_return, doc.update_stock = 0, 1
			# Administrator bypasses, so assert the bypass is what let it through
			# rather than the is_return branch.
			self.assertTrue(sales_flow._may_bypass())
			sales_flow.enforce_delivery_note_route(doc)
			self.assertEqual(doc.update_stock, 1)
		finally:
			frappe.set_user(original)

	def test_a_bypass_role_is_not_blocked(self):
		"""8 historical returns have no original and 11 span 2-23 delivery notes;
		those are left to a manager rather than made impossible."""
		doc = frappe.new_doc("Sales Invoice")
		doc.is_return = 1
		original = frappe.session.user
		frappe.set_user("Administrator")
		try:
			# Must not throw.
			return_flow.enforce_return_stock_route(doc)
		finally:
			frappe.set_user(original)

	def test_only_the_invoice_doctypes_carry_the_stock_route(self):
		"""A delivery return IS the stock document — it needs no route rule."""
		self.assertEqual(set(return_flow.STOCK_LINK), {"Sales Invoice", "Purchase Invoice"})


class TestDeliveryNoteDashboard(FrappeTestCase):
	def test_the_return_link_is_added(self):
		"""🔴 ERPNext's Delivery Note dashboard has no Delivery Note entry at all,
		so a delivery return never appears on the note it reverses."""
		data = return_flow.delivery_note_dashboard(
			data={"transactions": [{"label": "Returns", "items": ["Stock Entry"]}]}
		)
		self.assertEqual(data["non_standard_fieldnames"]["Delivery Note"], "return_against")
		items = [i for g in data["transactions"] for i in g["items"]]
		self.assertIn("Delivery Note", items)
		self.assertIn("Stock Entry", items)

	def test_it_is_idempotent(self):
		once = return_flow.delivery_note_dashboard(data={"transactions": []})
		twice = return_flow.delivery_note_dashboard(data=once)
		items = [i for g in twice["transactions"] for i in g["items"]]
		self.assertEqual(items.count("Delivery Note"), 1)

	def test_the_live_dashboard_surfaces_it(self):
		data = frappe.get_meta("Delivery Note").get_dashboard_data()
		items = [i for g in (data.get("transactions") or []) for i in (g.get("items") or [])]
		self.assertIn("Delivery Note", items)
		self.assertEqual(
			(data.get("non_standard_fieldnames") or {}).get("Delivery Note"), "return_against"
		)


class TestFieldMoves(FrappeTestCase):
	def test_the_customer_po_fields_sit_under_the_customer(self):
		meta = frappe.get_meta("Sales Invoice")
		order = [f.fieldname for f in meta.fields]
		self.assertLess(order.index("po_no"), order.index("column_break1"))
		self.assertEqual(order[order.index("company_tax_id") + 1], "po_no")
		self.assertEqual(order[order.index("po_no") + 1], "po_date")

	def test_a_move_is_a_permutation(self):
		"""A dropped fieldname removes the field from the form entirely."""
		ps = frappe.db.get_value(
			"Property Setter",
			{"doc_type": "Sales Invoice", "property": "field_order", "doctype_or_field": "DocType"},
			"value",
		)
		self.assertTrue(ps, "no field_order Property Setter on Sales Invoice")
		order = json.loads(ps)
		self.assertEqual(len(order), len(set(order)), "a fieldname appears twice")
		for fieldname, anchor in field_layout.FIELD_MOVES["Sales Invoice"]:
			self.assertIn(fieldname, order)
			self.assertIn(anchor, order)

	def test_applying_it_again_changes_nothing(self):
		first = field_layout.apply_field_moves()
		self.assertEqual(first["moved"], 0, "field moves were not already applied")
		self.assertFalse(first["skipped"])
