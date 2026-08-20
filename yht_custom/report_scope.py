# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Branch scoping for reports.

`permission_query_conditions` does NOT apply to a Script Report. A Script Report
runs its own SQL, so nothing in `branch_filters` reaches it — a report that does
not scope itself shows a branch user every branch's data, whatever the list views
do. That asymmetry is the whole reason the report pack is Script Reports rather
than Query Reports: a Query Report cannot call this module at all.

The scope resolved here is deliberately the SAME source of truth the list filters
use — `branch_filters.get_branch_warehouses` and `get_branch_peers` — so a report
and the list view it drills into can never disagree about what the branch owns.
"""

import frappe
from frappe import _

from yht_custom.branch_filters import BYPASS_ROLES, get_branch_peers, get_branch_warehouses


def is_restricted(user: str | None = None) -> bool:
	"""True when this user's reports must be scoped to their branch."""
	user = user or frappe.session.user
	if user == "Administrator":
		return False
	if set(frappe.get_roles(user)) & set(BYPASS_ROLES):
		return False
	return bool(frappe.db.exists("Branch Configuration User", {"user": user}))


def allowed_warehouses(user: str | None = None) -> list[str]:
	"""Warehouses this user's reports may read. Empty list means "no restriction"."""
	return get_branch_warehouses(user)


def allowed_owners(user: str | None = None) -> list[str]:
	"""The branch roster, used the same way the list filters use it.

	A document with no warehouse on it — 143 Sales Invoice Items on this site have
	a blank `warehouse` — would otherwise vanish from every branch report while
	still showing in the list view.
	"""
	user = user or frappe.session.user
	return get_branch_peers(user) or [user]


def resolve_warehouses(chosen: str | None, user: str | None = None) -> list[str]:
	"""Reconcile a user-picked warehouse filter with what the branch may see.

	Returns the warehouse list to filter on, or ``[]`` for "do not filter by
	warehouse at all". Throws when a restricted user names a warehouse outside
	their branch — silently returning an empty report would read as "no sales"
	rather than "not yours".
	"""
	allowed = allowed_warehouses(user)

	if chosen:
		chosen_set = _expand_group(chosen)
		if allowed:
			outside = chosen_set - set(allowed)
			if outside:
				frappe.throw(
					_("Warehouse {0} is not in your branch.").format(frappe.bold(chosen)),
					title=_("Outside your branch"),
				)
		return sorted(chosen_set)

	return allowed


def _expand_group(warehouse: str) -> set[str]:
	"""A group warehouse stands for every leaf under it.

	`All Warehouses - KATC` is a group on this site; filtering on it literally
	would match nothing, because no transaction posts to a group warehouse.
	"""
	if not frappe.db.get_value("Warehouse", warehouse, "is_group"):
		return {warehouse}

	lft, rgt = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt"])
	leaves = frappe.get_all(
		"Warehouse",
		filters={"lft": [">=", lft], "rgt": ["<=", rgt], "is_group": 0},
		pluck="name",
	)
	return set(leaves) or {warehouse}


def company_filter(filters: dict) -> str:
	"""The company to report on, defaulted rather than left blank.

	A blank company on a single-company site is harmless, but the moment a second
	company exists an unfiltered report silently mixes them.
	"""
	return (
		filters.get("company")
		or frappe.defaults.get_user_default("Company")
		or frappe.defaults.get_global_default("company")
	)
