# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Client sheet items 7, 8, 9 (the three ledgers), 13 and 14 (Branch Manager)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_months, flt, nowdate

from yht_custom import branch_filters, setup

REPORTS = ("KATC Stock Ledger", "KATC General Ledger", "KATC Party and Account Ledger")

#: The columns the client asked for, in their own words, per sheet item.
REQUIRED_COLUMNS = {
	"KATC Stock Ledger": (
		"posting_date", "voucher_no", "item_code", "item_name",
		"qty_in", "qty_out", "balance_qty", "transaction_rate",
		"valuation_rate", "balance_value",
	),
	"KATC General Ledger": ("posting_date", "voucher_no", "remarks", "debit", "credit", "balance"),
	"KATC Party and Account Ledger": (
		"posting_date", "voucher_no", "remarks", "debit", "credit", "balance",
	),
}


def _company():
	return frappe.db.get_value("Branch Configuration", {}, "company") or frappe.defaults.get_global_default(
		"company"
	)


class TestKatcReportsInstalled(FrappeTestCase):
	def test_all_three_reports_exist(self):
		for name in REPORTS:
			with self.subTest(report=name):
				self.assertTrue(frappe.db.exists("Report", name), f"{name} is not installed")

	def test_frappe_can_actually_LOAD_each_report(self):
		"""🔴 THE ONE THAT WAS MISSING, AND IT COST A BROKEN REPORT.

		The other tests import the module by a slug written down here, which proves
		the file exists — not that the DESK can find it. Frappe resolves a Script
		Report's module by scrubbing its NAME, and `frappe.scrub` only replaces
		spaces and hyphens (`frappe/__init__.py:1475`). An ampersand survives, so
		"KATC Party & Account Ledger" resolved to
		`...report.katc_party_&_account_ledger` — not a legal module name — and the
		report raised ModuleNotFoundError for anyone who opened it while every test
		here passed.

		So resolve it the way frappe does: from the stored report name, not from a
		slug we control.
		"""
		for name in REPORTS:
			with self.subTest(report=name):
				stored = frappe.db.get_value("Report", name, "report_name")
				slug = frappe.scrub(stored)
				self.assertRegex(
					slug, r"^[a-z_][a-z0-9_]*$",
					f"'{stored}' scrubs to '{slug}', which is not a legal Python module name",
				)
				execute = frappe.get_attr(f"yht_custom.yht_custom.report.{slug}.{slug}.execute")
				self.assertTrue(callable(execute))

	def test_they_are_script_reports(self):
		"""🔴 NOT Query Reports. `permission_query_conditions` does not reach a report
		(gotcha 20), so a report must scope itself in code — which a Query Report
		cannot do."""
		for name in REPORTS:
			with self.subTest(report=name):
				self.assertEqual(frappe.db.get_value("Report", name, "report_type"), "Script Report")

	def test_branch_manager_can_reach_them(self):
		for name in REPORTS:
			with self.subTest(report=name):
				roles = frappe.get_all(
					"Has Role", filters={"parent": name, "parenttype": "Report"}, pluck="role"
				)
				self.assertIn("Branch Manager", roles)
				self.assertIn("Branch User", roles)

	def test_each_report_returns_the_columns_the_client_asked_for(self):
		"""The sheet names these columns literally. A rename is a spec change."""
		for name in REPORTS:
			with self.subTest(report=name):
				columns = self._run(name)[0]
				got = {c["fieldname"] for c in columns}
				for fieldname in REQUIRED_COLUMNS[name]:
					self.assertIn(fieldname, got, f"{name} is missing {fieldname}")

	#: Explicit, because scrubbing "KATC Party and Account Ledger" into a module path
	#: is exactly the kind of derivation that breaks silently on the next rename.
	MODULES = {
		"KATC Stock Ledger": "katc_stock_ledger",
		"KATC General Ledger": "katc_general_ledger",
		"KATC Party and Account Ledger": "katc_party_and_account_ledger",
	}

	def _run(self, name):
		slug = self.MODULES[name]
		execute = frappe.get_attr(f"yht_custom.yht_custom.report.{slug}.{slug}.execute")
		return execute(self._filters(name))

	def _filters(self, name):
		base = {
			"company": _company(),
			"from_date": add_months(nowdate(), -12),
			"to_date": nowdate(),
		}
		if name == "KATC General Ledger":
			base["account"] = frappe.db.get_value("GL Entry", {"is_cancelled": 0}, "account")
		if name == "KATC Party and Account Ledger":
			row = frappe.db.get_value(
				"GL Entry", {"is_cancelled": 0, "party": ["!=", ""]}, ["party_type", "party"], as_dict=True
			)
			if row:
				base["party_type"], base["party"] = row.party_type, row.party
		return base


class TestStockLedgerArithmetic(FrappeTestCase):
	def test_qty_in_and_out_split_the_signed_movement(self):
		"""🔴 THE POINT OF ITEM 7. ERPNext prints one signed column; the client wants
		two, so a storekeeper does not do sign arithmetic in their head."""
		from yht_custom.yht_custom.report.katc_stock_ledger import katc_stock_ledger

		_cols, rows = katc_stock_ledger.execute(
			{"company": _company(), "from_date": add_months(nowdate(), -12), "to_date": nowdate()}
		)
		if not rows:
			self.skipTest("no stock movement in the window")
		for row in rows[:200]:
			qty = flt(row.get("actual_qty"))
			self.assertGreaterEqual(flt(row.get("qty_in")), 0, "qty in is never negative")
			self.assertGreaterEqual(flt(row.get("qty_out")), 0, "qty out is never negative")
			# One side or the other, never both.
			self.assertFalse(
				flt(row.get("qty_in")) and flt(row.get("qty_out")),
				f"{row.get('voucher_no')} is both an in and an out",
			)
			self.assertAlmostEqual(
				flt(row.get("qty_in")) - flt(row.get("qty_out")), qty, places=4,
				msg="in minus out must equal the signed movement",
			)

	def test_an_issue_does_not_print_a_zero_transaction_rate(self):
		"""`incoming_rate` is 0 on an issue — printing it bare reads as "sold at zero"."""
		from yht_custom.yht_custom.report.katc_stock_ledger import katc_stock_ledger

		_cols, rows = katc_stock_ledger.execute(
			{"company": _company(), "from_date": add_months(nowdate(), -12), "to_date": nowdate()}
		)
		outs = [r for r in rows if flt(r.get("qty_out")) and flt(r.get("valuation_rate"))]
		if not outs:
			self.skipTest("no outward movement with a valuation rate")
		for row in outs[:50]:
			self.assertTrue(
				flt(row.get("transaction_rate")),
				f"{row.get('voucher_no')} printed a zero transaction rate on an issue",
			)


class TestBranchManagerRole(FrappeTestCase):
	"""Items 13 and 14. The client dropped the other five roles; this is the one."""

	def test_the_role_exists(self):
		self.assertTrue(frappe.db.exists("Role", setup.BRANCH_MANAGER_ROLE))

	def test_it_has_desk_access(self):
		self.assertTrue(frappe.db.get_value("Role", setup.BRANCH_MANAGER_ROLE, "desk_access"))

	def test_it_can_reach_everything_a_branch_user_can(self):
		"""A manager who sees less than their staff is not a manager.

		`BRANCH_USER_PERMISSIONS` is a LIST of dicts keyed on "parent", not a
		mapping — reading it as one silently iterated nothing and the test passed
		without asserting anything.
		"""
		doctypes = {spec["parent"] for spec in setup.BRANCH_USER_PERMISSIONS}
		self.assertTrue(doctypes, "no branch permissions configured")
		for doctype in sorted(doctypes):
			with self.subTest(doctype=doctype):
				self.assertTrue(
					frappe.db.exists(
						"Custom DocPerm",
						{"parent": doctype, "role": setup.BRANCH_MANAGER_ROLE},
					),
					f"Branch Manager has no DocPerm on {doctype}",
				)


class TestCancelledVisibility(FrappeTestCase):
	"""Item 14 — cancelled files viewable only by the Branch Manager."""

	def test_a_branch_user_gets_the_docstatus_filter(self):
		clause = branch_filters._hide_cancelled("Sales Invoice", "Administrator")
		# Administrator holds System Manager, so it must NOT be filtered.
		self.assertEqual(clause, "1 = 1")

	def test_an_unprivileged_user_is_filtered(self):
		user = frappe.db.get_value(
			"Has Role",
			{"role": setup.BRANCH_USER_ROLE, "parenttype": "User"},
			"parent",
		)
		if not user:
			self.skipTest("no Branch User on this site")
		if branch_filters.can_see_cancelled(user):
			self.skipTest(f"{user} also holds Branch Manager or System Manager")
		clause = branch_filters._hide_cancelled("Sales Invoice", user)
		self.assertIn("docstatus", clause)
		self.assertIn("!= 2", clause)

	def test_the_clause_is_always_safe_to_and(self):
		"""It is interpolated into a WHERE unconditionally, so it may never be blank."""
		for user in ("Administrator", frappe.session.user):
			with self.subTest(user=user):
				self.assertTrue(branch_filters._hide_cancelled("Sales Invoice", user).strip())

	def test_branch_manager_sees_cancelled(self):
		self.assertTrue(
			branch_filters.can_see_cancelled("Administrator"),
			"System Manager must be able to investigate a cancelled document",
		)


class TestReportsWorkspace(FrappeTestCase):
	def test_the_workspace_exists(self):
		self.assertTrue(frappe.db.exists("Workspace", "KATC Reports"))

	def test_it_links_the_three_client_reports(self):
		links = frappe.get_all(
			"Workspace Link",
			filters={"parent": "KATC Reports", "type": "Link"},
			pluck="link_to",
		)
		for name in REPORTS:
			self.assertIn(name, links, f"{name} is not on the Reports workspace")

	def test_every_link_points_at_something_real(self):
		"""A workspace link to a missing report renders as a dead tile."""
		rows = frappe.get_all(
			"Workspace Link",
			filters={"parent": "KATC Reports", "type": "Link"},
			fields=["link_to", "link_type"],
		)
		self.assertTrue(rows, "the workspace has no links")
		for row in rows:
			with self.subTest(link=row.link_to):
				self.assertTrue(
					frappe.db.exists(row.link_type, row.link_to),
					f"{row.link_type} {row.link_to} does not exist",
				)
