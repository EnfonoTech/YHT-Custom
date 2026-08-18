# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Data for the branch-user dashboard page."""

import frappe
from frappe.utils import get_first_day, today

from yht_custom.branch_filters import get_branch_warehouses


@frappe.whitelist()
def get_dashboard_data() -> dict:
	"""Headline figures for the signed-in user's branch.

	Scoped by the same warehouse list the list views use, so the tile totals and
	the lists a user can open always agree.
	"""
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	warehouses = get_branch_warehouses(user)
	# An empty warehouse list means unrestricted (admin, or not branch-mapped).
	unrestricted = not warehouses

	config = frappe.get_all("Branch Configuration User", filters={"user": user}, pluck="parent", limit=1)
	branch = frappe.db.get_value("Branch Configuration", config[0], "branch") if config else None
	company = frappe.db.get_value("Branch Configuration", config[0], "company") if config else None
	company = company or frappe.defaults.get_user_default("company")

	data = {
		"user": user,
		"branch": branch,
		"company": company,
		"warehouses": warehouses,
		"is_admin": bool(roles & {"System Manager", "Stock Manager"}),
		"is_branch_user": "Branch User" in roles,
	}

	day = today()
	month_start = get_first_day(day)

	data["sales_today"] = _sales_total(day, day, warehouses, unrestricted)
	data["sales_mtd"] = _sales_total(month_start, day, warehouses, unrestricted)
	data["invoices_mtd"] = _sales_count(month_start, day, warehouses, unrestricted)
	data["outstanding"] = _outstanding(company)
	data["draft_counts"] = _draft_counts(warehouses, unrestricted)

	return data


def _warehouse_clause(warehouses, unrestricted):
	"""Return (sql_fragment, params) — parameterised, never interpolated."""
	if unrestricted:
		return "", []
	placeholders = ", ".join(["%s"] * len(warehouses))
	return f" AND si.set_warehouse IN ({placeholders})", list(warehouses)


def _sales_total(from_date, to_date, warehouses, unrestricted) -> float:
	clause, params = _warehouse_clause(warehouses, unrestricted)
	rows = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(si.grand_total), 0)
		FROM `tabSales Invoice` si
		WHERE si.docstatus = 1 AND si.posting_date BETWEEN %s AND %s{clause}
		""",
		[from_date, to_date, *params],
	)
	return rows[0][0] or 0


def _sales_count(from_date, to_date, warehouses, unrestricted) -> int:
	clause, params = _warehouse_clause(warehouses, unrestricted)
	rows = frappe.db.sql(
		f"""
		SELECT COUNT(*)
		FROM `tabSales Invoice` si
		WHERE si.docstatus = 1 AND si.posting_date BETWEEN %s AND %s{clause}
		""",
		[from_date, to_date, *params],
	)
	return rows[0][0] or 0


def _outstanding(company) -> float:
	if not company:
		return 0
	rows = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(outstanding_amount), 0)
		FROM `tabSales Invoice`
		WHERE docstatus = 1 AND company = %s AND outstanding_amount > 0
		""",
		[company],
	)
	return rows[0][0] or 0


def _draft_counts(warehouses, unrestricted) -> dict:
	"""Drafts waiting on the user, so the dashboard shows work-in-hand.

	Counted through ``get_list``, which applies ``permission_query_conditions`` —
	so branch scoping is inherited rather than re-implemented, and the number
	always matches what the user sees when they open the list.
	"""
	out = {}
	for doctype in ("Quotation", "Sales Order", "Delivery Note", "Sales Invoice"):
		try:
			out[doctype] = len(
				frappe.get_list(doctype, filters={"docstatus": 0}, limit_page_length=0, pluck="name")
			)
		except frappe.PermissionError:
			out[doctype] = 0
	return out
