# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Tests for the return policy — negation, the stock route, series, layout."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import field_layout, return_flow, setup_branch_series

BRANCH = "_Test YHT Return Branch"
USER = "_test_yht_return_user@example.invalid"


def _first(doctype, filters=None):
	return frappe.db.get_value(doctype, filters or {}, "name")


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


def _make_branch_user(test):
	"""A user with NO bypass role.

	🔴 Without this every route test passes vacuously: `enforce_return_stock_route`
	returns immediately for a bypass role, and the suite runs as Administrator, which
	`_is_bypass` treats as one.
	"""
	company = _first("Company")
	warehouse = frappe.db.get_value(
		"Warehouse", {"company": company, "is_group": 0, "disabled": 0}, "name"
	)
	if not (company and warehouse):
		test.skipTest("site lacks a company or warehouse")

	if not frappe.db.exists("Branch", BRANCH):
		frappe.get_doc({"doctype": "Branch", "branch": BRANCH}).insert(ignore_permissions=True)
	if not frappe.db.exists("User", USER):
		frappe.get_doc(
			{"doctype": "User", "email": USER, "first_name": "Return", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	if frappe.db.exists("Branch Configuration", BRANCH):
		frappe.delete_doc("Branch Configuration", BRANCH, force=1, ignore_permissions=True)
	cfg = frappe.new_doc("Branch Configuration")
	cfg.branch, cfg.company = BRANCH, company
	cfg.append("warehouse", {"warehouse": warehouse})
	cfg.append("user", {"user": USER, "role": "Branch User"})
	cfg.insert(ignore_permissions=True)
	frappe.clear_cache(user=USER)
	return company


class TestReturnRouteBlockers(FrappeTestCase):
	"""One test per blocker the adversarial review confirmed on 2026-08-26.

	Every one of these reproduced against real data before the fix.
	"""

	def setUp(self):
		self.company = _make_branch_user(self)
		frappe.set_user(USER)
		from yht_custom.sales_flow import _may_bypass

		if _may_bypass():
			frappe.set_user("Administrator")
			self.skipTest("test user holds a bypass role — the guard would no-op")

	def tearDown(self):
		frappe.set_user("Administrator")
		if hasattr(frappe.local, "yht_branch_config_cache"):
			delattr(frappe.local, "yht_branch_config_cache")
		frappe.db.rollback()

	def _return_of(self, original_name, doctype="Sales Invoice"):
		original = frappe.get_doc(doctype, original_name)
		doc = frappe.new_doc(doctype)
		doc.company = original.company
		if doctype == "Sales Invoice":
			doc.customer = original.customer
		else:
			doc.supplier = original.supplier
		doc.is_return, doc.return_against = 1, original_name
		return original, doc

	# ---------------------------------------------------- blocker 1 + major

	def test_an_expense_debit_note_is_not_refused(self):
		"""🔴 It was, and unsatisfiably.

		An expense bill is itemless by design, and the route the guard demanded — a
		Purchase Receipt — cannot hold an itemless row, because
		`Purchase Receipt Item.item_code` is mandatory while `Purchase Invoice Item`'s
		is not. That asymmetry is the whole reason an expense invoice IS a flagged
		Purchase Invoice. 345 expense invoices plus every future one were affected.
		"""
		doc = frappe.new_doc("Purchase Invoice")
		doc.is_return = 1
		doc.custom_is_expense_invoice = 1
		doc.append("items", {"item_name": "Rent", "qty": -1, "rate": 100})
		# Must not throw.
		return_flow.enforce_return_stock_route(doc)

	def test_a_return_of_something_never_shipped_is_not_refused(self):
		"""🔴 'The original did not carry its own stock' is NOT 'it went out on a note'.

		It equally means nothing moved at all. 150 sales invoices and 366 purchase
		invoices on this site have no stock document behind them.
		"""
		doc = frappe.new_doc("Sales Invoice")
		doc.is_return = 1
		doc.return_against = None
		doc.append("items", {"item_name": "Consulting", "qty": -1, "rate": 500})
		# No original to point at, so nothing shipped — must not throw.
		return_flow.enforce_return_stock_route(doc)

	# ------------------------------------------------------------ blocker 2

	def test_a_stock_moving_return_cannot_be_typed_by_hand(self):
		"""🔴 THE HOLE THIS CHANGE OPENED, AND THEN CLOSED.

		Exempting returns from the forward rule meant a branch user could tick
		`is_return` against any of 950 legacy direct-stock invoices and post ANY item
		at ANY quantity into the warehouse — `update_stock` was left as typed and the
		return's own rows were never examined. ERPNext is no backstop: its over-return
		guard keys on `sales_invoice_item`, which a hand-typed row does not have.
		"""
		src = frappe.db.get_value(
			"Sales Invoice", {"docstatus": 1, "is_return": 0, "update_stock": 1}, "name"
		)
		if not src:
			self.skipTest("no direct-stock invoice on this site")

		original, doc = self._return_of(src)
		doc.update_stock = 1
		row = original.items[0]
		# A row that did NOT come from the original: no sales_invoice_item.
		doc.append("items", {"item_code": row.item_code, "qty": -1, "rate": row.rate,
		                     "uom": row.uom, "conversion_factor": row.conversion_factor})
		with self.assertRaises(frappe.ValidationError):
			return_flow.enforce_return_stock_route(doc)

	def test_a_mapped_stock_moving_return_is_allowed(self):
		"""The same document, built the supported way, must pass."""
		src = frappe.db.get_value(
			"Sales Invoice", {"docstatus": 1, "is_return": 0, "update_stock": 1}, "name"
		)
		if not src:
			self.skipTest("no direct-stock invoice on this site")

		original, doc = self._return_of(src)
		doc.update_stock = 1
		row = original.items[0]
		doc.append("items", {"item_code": row.item_code, "qty": -1, "rate": row.rate,
		                     "uom": row.uom, "conversion_factor": row.conversion_factor,
		                     "sales_invoice_item": row.name})
		return_flow.enforce_return_stock_route(doc)
		self.assertEqual(doc.update_stock, 1, "the goods must still come back on this document")

	# -------------------------------------------------------------- wording

	def test_the_purchase_side_gets_purchase_side_wording(self):
		"""A buyer has no Delivery Note, no Sales Return menu and no Issue Credit Note."""
		si_title, si_msg = return_flow.ROUTE_MESSAGE["Sales Invoice"]
		pi_title, pi_msg = return_flow.ROUTE_MESSAGE["Purchase Invoice"]
		self.assertIn("Delivery Note", si_msg)
		self.assertNotIn("Delivery Note", pi_msg)
		self.assertNotIn("Issue Credit Note", pi_msg)
		self.assertIn("Purchase Receipt", pi_msg)
		self.assertNotEqual(si_title, pi_title)

	# ----------------------------------------------------- every row, not any

	def test_one_linked_row_does_not_admit_the_others(self):
		"""🔴 It did. A single legitimate line carried unlimited unrelated ones through,
		and it was the one path that admitted a return with `return_against` blank —
		which switches off every ERPNext return check."""
		dn_return = frappe.db.get_value("Delivery Note", {"is_return": 1, "docstatus": 1}, "name")
		if not dn_return:
			self.skipTest("no delivery return on this site")

		doc = frappe.new_doc("Sales Invoice")
		doc.append("items", {"item_name": "linked", "qty": -1, "delivery_note": dn_return})
		doc.append("items", {"item_name": "stowaway", "qty": -1})
		self.assertFalse(
			return_flow._came_back_on_a_stock_return(doc),
			"a row with no delivery note behind it was carried through by a linked sibling",
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


class TestStockReturnEntryPoint(FrappeTestCase):
	"""A Delivery Note / Purchase Receipt return cannot start as a blank document.

	🔴 THE BUG THIS PINS. `is_return` is read_only = 1 AND no_copy = 1 on both stock
	doctypes, so nothing pre-ticks it — not a route option, not a filtered list's
	"+ Add", not frappe.new_doc. A branch user opening the returns list and using its
	own Add button got an ordinary KSDN- note, silently. The dashboard tiles pointed at
	that list, which made the wrong path the obvious one.
	"""

	def test_is_return_is_not_editable_on_the_stock_doctypes(self):
		"""If this ever flips upstream, the source picker becomes unnecessary."""
		for doctype in ("Delivery Note", "Purchase Receipt"):
			df = frappe.get_meta(doctype).get_field("is_return")
			with self.subTest(doctype=doctype):
				self.assertTrue(df.read_only, f"{doctype}.is_return is no longer read-only")
				self.assertTrue(df.no_copy, f"{doctype}.is_return is no longer no_copy")

	def test_is_return_IS_editable_on_the_invoices(self):
		"""Which is why those two get a blank-document entry point instead."""
		for doctype in ("Sales Invoice", "Purchase Invoice"):
			df = frappe.get_meta(doctype).get_field("is_return")
			with self.subTest(doctype=doctype):
				self.assertFalse(df.read_only, f"{doctype}.is_return became read-only")

	def test_the_js_asks_for_a_source_on_the_stock_doctypes(self):
		path = frappe.get_app_path("yht_custom", "public", "js", "sales_flow.js")
		src = open(path, encoding="utf-8").read()
		self.assertIn("new_stock_return", src)
		self.assertIn("open_mapped_doc", src, "the return must go through erpnext's mapper")
		for method in (
			"erpnext.stock.doctype.delivery_note.delivery_note.make_sales_return",
			"erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_return",
		):
			with self.subTest(method=method):
				self.assertIn(method, src)
		# the picker must exclude documents already fully returned
		self.assertIn("per_returned", src, "the source picker does not exclude spent documents")

	def test_the_named_mappers_exist_and_are_whitelisted(self):
		"""A typo in a method path only shows up when a user clicks the button."""
		for path in (
			"erpnext.stock.doctype.delivery_note.delivery_note.make_sales_return",
			"erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_return",
		):
			with self.subTest(path=path):
				fn = frappe.get_attr(path)
				# `frappe.whitelisted` is keyed by the FUNCTION OBJECT, not by its
				# dotted path — see frappe.is_whitelisted, which tests `method not in
				# whitelisted`. Checking the string silently never matches.
				self.assertIn(
					fn,
					frappe.whitelisted,
					f"{path} is not whitelisted — the desk could not call it",
				)

	def test_the_dashboard_tiles_do_not_open_a_blank_stock_return(self):
		path = frappe.get_app_path(
			"yht_custom", "yht_custom", "page", "yht_dashboard", "yht_dashboard.js"
		)
		src = open(path, encoding="utf-8").read()
		self.assertIn("data-yht-stock-return", src)
		# and must not send the user at a list whose Add button makes a plain note
		self.assertNotIn('doctype: "Delivery Note", mode: "list", filters: { is_return: 1 }', src)


class TestCreditNoteBacklink(FrappeTestCase):
	"""A credit note raised from a delivery return must find its original invoice.

	Reported on 2026-08-30 against a real chain the client built:
	KSDN-26-0534 → KSIN-26-0610 → KSDR-26-0025 → KSSR-26-0031. The credit note
	came out with `return_against` blank, so KSIN-26-0610 stayed **Unpaid** and
	neither document appeared in the other's Connections. Measured at the time:
	9 submitted credit notes on this site with the same gap.
	"""

	def tearDown(self):
		frappe.db.rollback()

	def test_every_backlink_field_exists(self):
		"""⚠️ Two of these are asymmetric and a guess gets them wrong.

		`Delivery Note Item` has `dn_detail` and no `delivery_note_item`;
		`Purchase Receipt Item` has `purchase_receipt_item` and no `pr_detail`.
		A rename upstream makes the linker a silent no-op, not an error.
		"""
		self.assertEqual(return_flow.assert_backlink_fields_exist(), [])

	def _live_chain(self):
		"""Find a real (delivery return, original invoice, original row) triple."""
		rows = frappe.db.sql(
			"""
			SELECT ret.name AS ret, ret_item.name AS ret_row, ret_item.dn_detail AS orig_row,
			       sii.parent AS invoice, sii.name AS invoice_row, si.customer, si.company
			FROM `tabDelivery Note` ret
			JOIN `tabDelivery Note Item` ret_item ON ret_item.parent = ret.name
			JOIN `tabSales Invoice Item` sii ON sii.dn_detail = ret_item.dn_detail
			JOIN `tabSales Invoice` si ON si.name = sii.parent AND si.docstatus = 1 AND si.is_return = 0
			WHERE ret.is_return = 1 AND ret.docstatus = 1 AND ret_item.dn_detail IS NOT NULL
			LIMIT 1
			""",
			as_dict=True,
		)
		if not rows:
			self.skipTest("no delivery return on this site is billed by exactly one invoice")
		return rows[0]

	def _credit_note(self, chain, **overrides):
		doc = frappe.new_doc("Sales Invoice")
		doc.customer = overrides.pop("customer", chain.customer)
		doc.company = overrides.pop("company", chain.company)
		doc.is_return = 1
		doc.append(
			"items",
			{
				"item_code": frappe.db.get_value("Sales Invoice Item", chain.invoice_row, "item_code"),
				"qty": -1,
				"delivery_note": overrides.pop("delivery_note", chain.ret),
				"dn_detail": overrides.pop("dn_detail", chain.ret_row),
			},
		)
		return doc

	def test_a_credit_note_from_a_delivery_return_finds_its_invoice(self):
		chain = self._live_chain()
		doc = self._credit_note(chain)
		return_flow.link_credit_note_to_original_invoice(doc)
		self.assertEqual(doc.return_against, chain.invoice)
		self.assertEqual(doc.items[0].sales_invoice_item, chain.invoice_row)

	def test_the_row_link_is_never_set_without_return_against(self):
		"""⚠️ `return_against` alone is WORSE than standalone.

		ERPNext's over-return guard keys on the row link; blank, it degrades from
		an error to a msgprint and a second full return would save.
		"""
		chain = self._live_chain()
		doc = self._credit_note(chain, dn_detail=None)
		return_flow.link_credit_note_to_original_invoice(doc)
		self.assertFalse(doc.return_against)
		self.assertFalse(doc.items[0].get("sales_invoice_item"))

	def test_a_hand_typed_credit_note_is_left_standalone(self):
		doc = frappe.new_doc("Sales Invoice")
		doc.is_return = 1
		doc.append("items", {"qty": -1})
		return_flow.link_credit_note_to_original_invoice(doc)
		self.assertFalse(doc.return_against)

	def test_a_note_mapped_from_a_FORWARD_delivery_note_is_left_alone(self):
		"""Billing a plain delivery note is a first sale, not a reversal."""
		chain = self._live_chain()
		forward = frappe.db.get_value("Delivery Note", chain.ret, "return_against")
		doc = self._credit_note(chain, delivery_note=forward)
		return_flow.link_credit_note_to_original_invoice(doc)
		self.assertFalse(doc.return_against)

	def test_a_party_mismatch_is_left_standalone(self):
		"""ERPNext throws on a mismatched party — a wrong link is a hard error."""
		chain = self._live_chain()
		other = frappe.db.get_value(
			"Customer", {"name": ["!=", chain.customer]}, "name"
		)
		if not other:
			self.skipTest("only one customer on this site")
		doc = self._credit_note(chain, customer=other)
		return_flow.link_credit_note_to_original_invoice(doc)
		self.assertFalse(doc.return_against)

	def test_an_already_linked_note_is_not_rewritten(self):
		chain = self._live_chain()
		doc = self._credit_note(chain)
		doc.return_against = "SOME-OTHER-INVOICE"
		return_flow.link_credit_note_to_original_invoice(doc)
		self.assertEqual(doc.return_against, "SOME-OTHER-INVOICE")

	def test_a_plain_invoice_is_untouched(self):
		chain = self._live_chain()
		doc = self._credit_note(chain)
		doc.is_return = 0
		return_flow.link_credit_note_to_original_invoice(doc)
		self.assertFalse(doc.return_against)

	def test_the_linker_runs_before_the_route_and_negate_rules(self):
		"""Both later rules reason about a note that must already know its original."""
		from yht_custom import hooks

		for doctype in ("Sales Invoice", "Purchase Invoice"):
			with self.subTest(doctype=doctype):
				chain = hooks._FLOW_EVENTS[doctype]["before_validate"]
				link = chain.index("yht_custom.return_flow.link_credit_note_to_original_invoice")
				route = chain.index("yht_custom.return_flow.enforce_return_stock_route")
				negate = chain.index("yht_custom.return_flow.negate_return_quantities")
				self.assertLess(link, route)
				self.assertLess(link, negate)

	def test_an_existing_credit_note_is_not_mistaken_for_the_original(self):
		"""🔴 Reproduced: this made the linker bail on a real chain.

		A credit note already raised against the same original row carries the SAME
		stock-row link, so it lands in the candidate set beside the invoice. Original
		row 177m1l8c9h matches both KSIN-24-6950 and the credit note KSSR-24-1027;
		counting before filtering returns saw two invoices and gave up.
		"""
		twice = frappe.db.sql(
			"""
			SELECT ret_item.dn_detail AS orig_row
			FROM `tabDelivery Note Item` ret_item
			JOIN `tabDelivery Note` ret ON ret.name = ret_item.parent
			     AND ret.is_return = 1 AND ret.docstatus = 1
			JOIN `tabSales Invoice Item` sii ON sii.dn_detail = ret_item.dn_detail
			JOIN `tabSales Invoice` si ON si.name = sii.parent AND si.docstatus = 1
			WHERE ret_item.dn_detail IS NOT NULL
			GROUP BY ret_item.dn_detail
			HAVING SUM(si.is_return = 1) > 0 AND SUM(si.is_return = 0) = 1
			LIMIT 1
			""",
			as_dict=True,
		)
		if not twice:
			self.skipTest("no original row on this site is billed and credited")
		rows = frappe.db.get_all(
			"Sales Invoice Item",
			filters={"dn_detail": twice[0].orig_row, "docstatus": 1},
			fields=["name", "parent"],
		)
		self.assertGreater(len(rows), 1, "fixture must be ambiguous to be worth testing")

		config = dict(return_flow.CREDIT_NOTE_BACKLINK["Sales Invoice"], _doctype="Sales Invoice")
		forward = [
			r for r in rows
			if not frappe.db.get_value("Sales Invoice", r.parent, "is_return")
		]
		self.assertEqual(len(forward), 1)

		ret_row = frappe.db.get_value(
			"Delivery Note Item", {"dn_detail": twice[0].orig_row}, "name"
		)
		row = frappe.new_doc("Sales Invoice").append("items", {})
		row.delivery_note = frappe.db.get_value("Delivery Note Item", ret_row, "parent")
		row.dn_detail = ret_row
		self.assertEqual(
			return_flow._original_invoice_row_for(row, config),
			(forward[0].parent, forward[0].name),
		)
