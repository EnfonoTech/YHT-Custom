# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""`ignore_user_permissions` Property Setters — layer 5 of the permission stack.

## Why these are needed

Frappe enforces User Permissions at the **link level**: if a branch user has a
User Permission for `Khobar Store` and a document's `set_warehouse` holds
`Stores`, Frappe refuses to open the document at all — a bare "Not permitted".
That fires constantly in normal use, because global defaults, Item Defaults and
existing documents all reference warehouses the user was never granted.

`ignore_user_permissions = 1` on those link fields stops the link-level block.

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

Layer 1 is what makes this safe. **Never ship these Property Setters without it**
— and both read their field list from `branch_fields`, so the two cannot drift.
"""

import frappe

from yht_custom.branch_fields import all_scoped_pairs


def setup_ignore_user_permissions() -> dict:
	"""Stamp ignore_user_permissions=1 on every branch-scoped link field.

	Idempotent: ``frappe.make_property_setter`` always inserts, so existing rows
	are detected and updated here rather than letting a second ``after_migrate``
	create duplicates.
	"""
	applied, already, failed = 0, 0, []

	for doctype, fieldname in all_scoped_pairs():
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
			else:
				already += 1
			continue

		try:
			# frappe.make_property_setter takes an args DICT — the positional-argument
			# form belongs to property_setter.make_property_setter, a different
			# function. Passing positionals here raises "got multiple values for
			# argument 'validate_fields_for_doctype'".
			frappe.make_property_setter(
				{
					"doctype": doctype,
					"fieldname": fieldname,
					"property": "ignore_user_permissions",
					"value": "1",
					"property_type": "Check",
				},
				validate_fields_for_doctype=False,
			)
			applied += 1
		except Exception as e:
			failed.append(f"{doctype}.{fieldname}: {type(e).__name__} {e}")

	if failed:
		frappe.log_error(
			"yht_custom.setup_property_setters failures:\n" + "\n".join(failed),
			"Branch Property Setters",
		)

	return {"applied": applied, "already_set": already, "failed": failed}
