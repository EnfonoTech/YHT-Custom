# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""`ignore_user_permissions` Property Setters — layer 5 of the permission stack.

## Why these are needed

Frappe enforces User Permissions at the **link level**: if a branch user has a
User Permission for `Khobar Store` and a document's `set_warehouse` holds
`Stores`, Frappe refuses to open the document at all — a bare "Not permitted".
That fires constantly in normal use, because global defaults, Item Defaults and
existing documents all reference warehouses the user was never granted.

Setting `ignore_user_permissions = 1` on those link fields stops the link-level
block.

## What that costs, and how it is paid for

**It also removes the write-side restriction on those fields.** On its own it
would let a branch user pick any warehouse in the company. That is not
acceptable, so the restriction is re-established elsewhere:

1. `branch_guard.validate_branch_scope` — a **server-side** `validate` hook that
   rejects a warehouse or cost center outside the user's branch. This is the
   actual boundary.
2. `branch_filters` — list views only ever show the branch's own documents.
3. Form `set_query` filters — the pickers only offer permitted values. UX, not
   enforcement.

Layer 1 is what makes this safe. Never ship these Property Setters without it.
"""

import frappe

#: (doctype, fieldname) pairs that reference a warehouse or cost center and must
#: not be link-blocked. Header fields AND item-row fields — an item row carrying
#: another branch's cost center blocks the whole document just as effectively.
IGNORE_USER_PERMISSION_FIELDS = [
	# --- selling ---
	("Quotation", "set_warehouse"),
	("Quotation Item", "warehouse"),
	("Quotation Item", "cost_center"),
	("Sales Order", "set_warehouse"),
	("Sales Order Item", "warehouse"),
	("Sales Order Item", "cost_center"),
	("Delivery Note", "set_warehouse"),
	("Delivery Note Item", "warehouse"),
	("Delivery Note Item", "target_warehouse"),
	("Delivery Note Item", "cost_center"),
	("Sales Invoice", "set_warehouse"),
	("Sales Invoice Item", "warehouse"),
	("Sales Invoice Item", "cost_center"),
	# --- buying ---
	("Purchase Order", "set_warehouse"),
	("Purchase Order Item", "warehouse"),
	("Purchase Order Item", "cost_center"),
	("Purchase Receipt", "set_warehouse"),
	("Purchase Receipt Item", "warehouse"),
	("Purchase Receipt Item", "cost_center"),
	("Purchase Invoice", "set_warehouse"),
	("Purchase Invoice Item", "warehouse"),
	("Purchase Invoice Item", "cost_center"),
	# --- stock ---
	("Stock Entry", "from_warehouse"),
	("Stock Entry", "to_warehouse"),
	("Stock Entry Detail", "s_warehouse"),
	("Stock Entry Detail", "t_warehouse"),
	("Stock Entry Detail", "cost_center"),
	("Material Request", "set_warehouse"),
	("Material Request", "set_from_warehouse"),
	("Material Request Item", "warehouse"),
	("Material Request Item", "from_warehouse"),
	# --- masters that seed the above ---
	("Item Default", "default_warehouse"),
	("Item Default", "buying_cost_center"),
	("Item Default", "selling_cost_center"),
	# --- accounting ---
	("Payment Entry", "cost_center"),
	("Journal Entry Account", "cost_center"),
]


def setup_ignore_user_permissions():
	"""Idempotently stamp ignore_user_permissions=1 on every field above.

	``frappe.make_property_setter`` always inserts, so duplicates are handled
	here rather than letting a second ``after_migrate`` throw.
	"""
	applied, skipped = 0, []

	for doctype, fieldname in IGNORE_USER_PERMISSION_FIELDS:
		if not frappe.db.exists("DocType", doctype):
			skipped.append(f"{doctype} (no such doctype)")
			continue

		meta = frappe.get_meta(doctype)
		field = meta.get_field(fieldname)
		if not field:
			# A field ERPNext renamed or dropped between versions — worth knowing
			# about rather than silently ignoring.
			skipped.append(f"{doctype}.{fieldname} (no such field)")
			continue

		existing = frappe.db.get_value(
			"Property Setter",
			{"doc_type": doctype, "field_name": fieldname, "property": "ignore_user_permissions"},
			["name", "value"],
			as_dict=True,
		)
		if existing:
			if str(existing.value) != "1":
				frappe.db.set_value("Property Setter", existing.name, "value", "1")
				applied += 1
			continue

		frappe.make_property_setter(
			doctype,
			fieldname,
			"ignore_user_permissions",
			"1",
			"Check",
			validate_fields_for_doctype=False,
		)
		applied += 1

	if skipped:
		frappe.log_error(
			"yht_custom.setup_property_setters skipped:\n" + "\n".join(skipped),
			"Branch Property Setters",
		)

	return {"applied": applied, "skipped": skipped}
