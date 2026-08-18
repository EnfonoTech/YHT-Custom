# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""One metadata-derived source of truth for branch-scoped link fields.

## Why this is derived rather than listed

The first version of this hard-coded the (doctype, fieldname) pairs. It was
wrong in both directions: it named two fields that do not exist in v15
(`Quotation.set_warehouse`, `Quotation Item.cost_center`) and it **missed more
than twenty that do** — `rejected_warehouse`, `set_target_warehouse`,
`set_from_warehouse`, `write_off_cost_center`, `Sales Order.cost_center` and
others.

Both directions matter, and the second is a security hole rather than a typo:
`setup_property_setters` switches off the link-level permission check on the
fields it knows about, and `branch_guard` re-enforces scope on the fields *it*
knows about. If those two lists disagree, the difference is a field a branch user
can point at another branch's warehouse with nothing checking it.

Deriving both from live metadata makes them agree by construction, and keeps them
correct across ERPNext upgrades that add or rename fields.
"""

import frappe

#: Doctypes whose warehouse / cost-center links are branch-scoped. A branch user
#: touching a doctype not listed here is governed by standard permissions alone.
SCOPED_DOCTYPES = (
	# selling
	"Quotation",
	"Quotation Item",
	"Sales Order",
	"Sales Order Item",
	"Delivery Note",
	"Delivery Note Item",
	"Sales Invoice",
	"Sales Invoice Item",
	# buying
	"Purchase Order",
	"Purchase Order Item",
	"Purchase Receipt",
	"Purchase Receipt Item",
	"Purchase Invoice",
	"Purchase Invoice Item",
	# stock
	"Stock Entry",
	"Stock Entry Detail",
	"Material Request",
	"Material Request Item",
	# accounting
	"Payment Entry",
	"Journal Entry Account",
	# masters that seed defaults onto the above
	"Item Default",
)

#: Parent doctypes the guard hooks onto, mapped to their item table fieldname.
#: Child rows are reached through the parent, never validated on their own.
GUARDED_PARENTS = {
	"Quotation": "items",
	"Sales Order": "items",
	"Delivery Note": "items",
	"Sales Invoice": "items",
	"Purchase Order": "items",
	"Purchase Receipt": "items",
	"Purchase Invoice": "items",
	"Stock Entry": "items",
	"Material Request": "items",
	"Payment Entry": None,
	"Journal Entry": "accounts",
}

LINK_TARGETS = ("Warehouse", "Cost Center")

#: Fields deliberately left out of the guard. Nothing yet — `supplier_warehouse`
#: and `set_reserve_warehouse` are subcontracting fields and stay IN scope,
#: because they still point at warehouses inside this company. Revisit only if
#: YHT starts subcontracting and needs a supplier-side warehouse outside the
#: branch tree.
GUARD_EXCLUDE: set[tuple[str, str]] = set()


def get_scoped_fields(doctype: str) -> dict[str, list[str]]:
	"""Link fields on ``doctype`` that point at a Warehouse or Cost Center.

	Returns ``{"Warehouse": [...], "Cost Center": [...]}``. Cached per request via
	``frappe.get_meta``, which is itself cached.
	"""
	if not frappe.db.exists("DocType", doctype):
		return {t: [] for t in LINK_TARGETS}

	out: dict[str, list[str]] = {t: [] for t in LINK_TARGETS}
	for field in frappe.get_meta(doctype).fields:
		if field.fieldtype == "Link" and field.options in LINK_TARGETS:
			out[field.options].append(field.fieldname)
	return out


def all_scoped_pairs() -> list[tuple[str, str]]:
	"""Every (doctype, fieldname) pair across ``SCOPED_DOCTYPES``."""
	pairs = []
	for doctype in SCOPED_DOCTYPES:
		fields = get_scoped_fields(doctype)
		for target in LINK_TARGETS:
			for fieldname in fields[target]:
				pairs.append((doctype, fieldname))
	return pairs
