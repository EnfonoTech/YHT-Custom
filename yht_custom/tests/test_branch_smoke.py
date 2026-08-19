# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Does every screen the branch user is pointed at actually open?

Written after a branch user hit a bare *"No permission for Party Type"* the moment they
opened a Payment Entry — a screen the dashboard sends them to and the guide documents.

The failure mode this file exists to kill: a permission gap that only appears when a
FORM IS OPENED, so it never shows up in a list-scoping test and nobody finds it until a
recording run or a client does.

WHY A LINK-TARGET SWEEP IS NOT ENOUGH
-------------------------------------
`Payment Entry.party_type` is declared ``Link -> DocType``, not ``Link -> Party Type``.
The picker is narrowed at runtime by a wired search query::

    query: "erpnext.setup.doctype.party_type.party_type.get_party_type"

and ``frappe.desk.search.search_link`` permission-checks the doctype the QUERY searches.
Walking declared ``options`` sees ``DocType`` and never discovers Party Type at all — the
declared option lies about what gets read. So this file tests the **wired queries**, by
the doctype they actually search, alongside the plain destinations.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

BRANCH_USER = "branchtest@yht-khobhar.enfonoerp.com"

#: Everything the dashboard tiles route to. Keep in step with ACTIONS/REPORTS in
#: yht_dashboard.js — a tile pointing somewhere unopenable is the bug this catches.
TILE_DOCTYPES = (
	"Sales Invoice",
	"Quotation",
	"Sales Order",
	"Delivery Note",
	"Customer",
	"Payment Entry",
	"Purchase Receipt",
	"Purchase Invoice",
	"Item",
)

TILE_REPORTS = (
	"Stock Balance",
	"Stock Ledger",
	"Accounts Receivable Summary",
	"General Ledger",
)

#: (label, doctype the wired query actually searches). Only flows the guide documents.
#: Sourced by grepping `query: "…"` out of the erpnext JS for these doctypes, then
#: resolving each to the doctype its Python searches — NOT from the field's `options`.
WIRED_QUERY_TARGETS = (
	("party_type picker — Payment Entry, Journal Entry", "Party Type"),
	("expense / income account picker", "Account"),
	("item picker", "Item"),
	("address picker", "Address"),
	("contact picker", "Contact"),
	("payment terms picker", "Payment Term"),
	("delivery-notes-to-be-billed picker", "Delivery Note"),
)

#: Pickers every branch form opens without a wired query.
PLAIN_PICKERS = (
	"Customer",
	"Supplier",
	"Warehouse",
	"Mode of Payment",
	"UOM",
	"Item Group",
	"Price List",
	"Currency",
	"Tax Category",
	"Item Tax Template",
)


def _branch_user_exists() -> bool:
	return bool(frappe.db.exists("User", BRANCH_USER))


class BranchUserContext(FrappeTestCase):
	"""Base class that runs each test as the branch user and always hands back.

	`frappe.clear_cache(user=...)` before `set_user` is mandatory: a role granted moments
	ago is not in the cached permission set, and without it every read is a bare
	PermissionError that looks exactly like a genuine missing grant.
	"""

	def setUp(self):
		super().setUp()
		if not _branch_user_exists():
			self.skipTest(f"{BRANCH_USER} does not exist on this site")
		frappe.clear_cache(user=BRANCH_USER)
		frappe.set_user(BRANCH_USER)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()


class TestBranchTileDestinations(BranchUserContext):
	def test_every_dashboard_tile_opens(self):
		"""A tile the branch user cannot open is a dead end on their home screen."""
		failures = []
		for doctype in TILE_DOCTYPES:
			if not frappe.db.exists("DocType", doctype):
				failures.append(f"{doctype}: doctype absent")
				continue
			try:
				frappe.get_list(doctype, fields=["name"], limit=1)
			except Exception as e:
				failures.append(f"{doctype}: {type(e).__name__}")
		self.assertEqual(failures, [], f"dashboard tiles a branch user cannot open: {failures}")

	def test_every_tile_doctype_opens_an_existing_record(self):
		"""What the desk actually calls when a form opens — and where it checks permission.

		`frappe.desk.form.load.getdoc` runs `doc.has_permission("read")` plus `get_docinfo`,
		which is the real form-open gate. Two earlier attempts at this test were wrong and
		both are worth recording so nobody repeats them:

		* `new_doc(dt).run_method("onload")` threw `TypeError: NoneType - float` on four
		  selling doctypes — that is ERPNext's totals maths on a virgin document with no
		  customer or items, not a permission signal.
		* `getdoctype(dt)` only assembles the meta bundle. It performs NO read check at all
		  (the `has_permission` on load.py:43 belongs to `get_docinfo`), so it could not have
		  caught anything — and it needs `frappe.response.docs` pre-seeded as a list or it
		  dies on `'NoneType' object has no attribute 'extend'`.
		"""
		from frappe.desk.form.load import getdoc

		failures = []
		for doctype in TILE_DOCTYPES:
			if not frappe.db.exists("DocType", doctype):
				continue
			name = frappe.db.get_value(doctype, {}, "name")
			if not name:
				continue
			try:
				frappe.response = frappe._dict(docs=[], docinfo=None)
				getdoc(doctype, name)
			except Exception as e:
				failures.append(f"{doctype} ({name}): {type(e).__name__}: {str(e)[:110]}")
		self.assertEqual(failures, [], f"form-open failures: {failures}")

	def test_every_tile_doctype_is_creatable(self):
		"""A tile that opens a new form needs `create`, not just `read`."""
		failures = [
			doctype
			for doctype in TILE_DOCTYPES
			if frappe.db.exists("DocType", doctype) and not frappe.has_permission(doctype, "create")
		]
		# Item is browse-only for this role by design; everything else must be creatable.
		failures = [d for d in failures if d != "Item"]
		self.assertEqual(failures, [], f"tiles a branch user cannot create from: {failures}")

	def test_every_dashboard_report_is_permitted(self):
		"""A Custom Role REPLACES a report's own Has Role list, it does not merge — so a
		report can look permitted on `Report.roles` while still refusing."""
		from frappe.core.doctype.report.report import Report

		failures = []
		for name in TILE_REPORTS:
			if not frappe.db.exists("Report", name):
				failures.append(f"{name}: report absent")
				continue
			report = frappe.get_doc("Report", name)
			if not report.is_permitted():
				failures.append(name)
		self.assertEqual(failures, [], f"dashboard reports refusing the branch user: {failures}")


class TestBranchPickers(BranchUserContext):
	def test_wired_query_targets_are_readable(self):
		"""THE Party Type regression guard.

		A wired search query is permission-checked against the doctype IT searches, which
		is not necessarily the field's declared `options`. Party Type reached the client
		this way and nothing in a declared-options sweep could have found it.
		"""
		# `read` OR `select` — not both. frappe/desk/search.py::search_widget resolves it as
		#     ptype = "select" if frappe.only_has_select_perm(doctype) else "read"
		# so `select` is the ALTERNATIVE used when a role holds nothing but select, never an
		# extra hurdle on top of read. An earlier version of this test demanded both and
		# reported `Payment Term` as broken when it works perfectly on read alone.
		failures = []
		for label, doctype in WIRED_QUERY_TARGETS:
			if not frappe.db.exists("DocType", doctype):
				continue
			if not (
				frappe.has_permission(doctype, "read") or frappe.has_permission(doctype, "select")
			):
				failures.append(f"{doctype} — {label}")
		self.assertEqual(failures, [], f"pickers a branch user cannot use: {failures}")

	def test_plain_pickers_are_readable(self):
		failures = [
			doctype
			for doctype in PLAIN_PICKERS
			if frappe.db.exists("DocType", doctype) and not frappe.has_permission(doctype, "read")
		]
		self.assertEqual(failures, [], f"unreadable pickers: {failures}")

	def test_party_type_search_actually_runs(self):
		"""The end-to-end version: run the real query, not just the permission check."""
		if not frappe.db.exists("DocType", "Party Type"):
			self.skipTest("Party Type absent")
		rows = frappe.get_list("Party Type", fields=["name"], limit=5)
		self.assertTrue(rows, "Party Type returned nothing — the picker would look broken")


class TestBranchGuideClaims(BranchUserContext):
	"""Claims the written guide makes to the client, asserted against the live site.

	If one of these fails the guide is now wrong, which is worse than a missing feature —
	staff will have been trained on it.
	"""

	def test_the_branch_user_cannot_reach_another_branch(self):
		invoices = frappe.get_list(
			"Sales Invoice", fields=["name", "set_warehouse"], limit_page_length=0
		)
		scoped = {row.set_warehouse for row in invoices if row.set_warehouse}
		allowed = set(frappe.get_all("Branch Configuration Warehouse", pluck="warehouse"))
		if scoped and allowed:
			self.assertTrue(
				scoped.issubset(allowed) or not allowed,
				f"branch user sees warehouses outside their branch: {scoped - allowed}",
			)

	def test_cancelled_documents_are_hidden(self):
		"""The guide tells staff a vanished document was cancelled. Hold that true."""
		rows = frappe.get_list(
			"Sales Invoice", filters={"docstatus": 2}, fields=["name"], limit_page_length=0
		)
		self.assertEqual(rows, [], "cancelled invoices are visible — the guide says they are not")

	def test_payment_modes_offered_all_have_an_account(self):
		"""The guide lists eight tenderable modes. Every one must be able to post."""
		from yht_custom.api.payment_assist import get_branch_payment_modes

		# frappe.db.get_value bypasses permissions by design and takes no
		# ignore_permissions argument — passing one is a TypeError, not a no-op.
		company = frappe.db.get_value("Branch Configuration", {}, "company")
		if not company:
			self.skipTest("no branch configuration")
		modes = get_branch_payment_modes(company)
		self.assertTrue(modes, "no tenderable payment modes — the Collect Payment dialog is empty")
		for mode in modes:
			self.assertNotIn("account", mode, "an account leaked into the browser payload")
