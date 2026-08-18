# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Item-group-wise item code generation.

MoM §2.4: item codes generated automatically, item-group-wise with a letter
prefix, replacing manual creation by individual salesmen.

**Why not `item_naming_by = "Naming Series"`.** That route makes
`Item.autoname` call `set_name_by_naming_series`, which *throws* when
`naming_series` is empty — so the moment the setting is flipped, every item
group without a configured series blocks item creation entirely. It also puts a
series picker in front of the user, which is the opposite of "generated
automatically".

Instead: `item_naming_by` stays `"Item Code"`, and this module fills `item_code`
in `before_insert`. That works because frappe runs `before_insert` *before*
`set_new_name()`, and ERPNext's `Item.autoname` ends with `self.name =
self.item_code` — so whatever we set becomes the document name.

The rule is deliberately conservative: **generate only when `item_code` is
empty.** A code the user typed on purpose is never overwritten, and a group with
no prefix configured behaves exactly as it does today. That means this can ship
before the client has decided all 28 prefixes.
"""

import frappe
from frappe import _
from frappe.model.naming import getseries
from frappe.utils import cint, cstr

#: Digits in the numeric part. 4 gives 9,999 items per group; the largest group
#: here holds 498.
CODE_DIGITS = 4

#: Custom Field on Item Group holding the letter prefix.
PREFIX_FIELD = "custom_item_code_prefix"


def get_group_prefix(item_group: str) -> str:
	"""The configured prefix for a group, or "" if it has none."""
	if not item_group:
		return ""
	return cstr(frappe.db.get_value("Item Group", item_group, PREFIX_FIELD) or "").strip().upper()


def _series_key(prefix: str) -> str:
	"""Counter key. Frappe keys ``tabSeries`` on this string, so including the
	prefix is what keeps each group's numbering independent."""
	return f"{prefix}-"


def peek_next_code(item_group: str) -> str:
	"""Next code WITHOUT consuming the counter — for showing the user a preview.

	Deliberately does not call ``getseries``: a preview that burns a number
	leaves gaps every time somebody opens a form and changes their mind.
	"""
	prefix = get_group_prefix(item_group)
	if not prefix:
		return ""

	# Raw parameterised SQL, not frappe.db.get_value: `tabSeries` is a bare table
	# with no DocType record behind it, so the query builder cannot resolve
	# metadata for it. Frappe's own naming.py talks to tabSeries the same way.
	row = frappe.db.sql("SELECT `current` FROM `tabSeries` WHERE `name` = %s", (_series_key(prefix),))
	current = cint(row[0][0]) if row and row[0][0] is not None else 0
	return f"{prefix}-{str(current + 1).zfill(CODE_DIGITS)}"


def generate_code(item_group: str) -> str:
	"""Consume the counter and return the next code. "" if no prefix."""
	prefix = get_group_prefix(item_group)
	if not prefix:
		return ""

	# getseries increments under `for update`, so concurrent inserts cannot
	# collide on the same number.
	for _attempt in range(10):
		code = f"{prefix}-{getseries(_series_key(prefix), CODE_DIGITS)}"
		if not frappe.db.exists("Item", code):
			return code
		# A code already taken means the counter drifted behind reality — most
		# likely a historical import that wrote codes without touching tabSeries.
		# Skipping forward is correct; looping forever is not.
	frappe.throw(
		_("Could not generate an item code for group {0} — the counter is behind existing item codes. Check the {1} on that Item Group.").format(
			frappe.bold(item_group), frappe.bold(_("Item Code Prefix"))
		)
	)


def set_item_code_from_group(doc, method=None):
	"""``Item.before_insert`` — fill item_code from the group's prefix.

	Never overwrites a code the user supplied.
	"""
	if doc.get("item_code"):
		return
	if doc.get("variant_of"):
		# Variants get their code from ERPNext's own variant logic.
		return

	code = generate_code(doc.get("item_group"))
	if code:
		doc.item_code = code


# ------------------------------------------------------------------ public API


@frappe.whitelist()
def preview_item_code(item_group: str) -> dict:
	"""What the next code for this group would be. Powers the Item form."""
	frappe.has_permission("Item", "create", throw=True)
	prefix = get_group_prefix(item_group)
	return {
		"prefix": prefix,
		"next_code": peek_next_code(item_group) if prefix else "",
		"configured": bool(prefix),
	}


@frappe.whitelist()
def get_prefix_coverage() -> dict:
	"""Which item groups still need a prefix — the implementer's checklist.

	Only leaf groups matter: items cannot be assigned to a group node.
	"""
	frappe.only_for(("System Manager", "Item Manager", "Stock Manager"))

	groups = frappe.get_all(
		"Item Group",
		filters={"is_group": 0},
		fields=["name", PREFIX_FIELD],
		order_by="name",
	)
	counts = dict(
		frappe.db.sql("select item_group, count(*) from tabItem group by item_group")
	)

	configured, missing, clashes = [], [], {}
	for g in groups:
		prefix = cstr(g.get(PREFIX_FIELD) or "").strip().upper()
		row = {"item_group": g["name"], "prefix": prefix, "items": counts.get(g["name"], 0)}
		if prefix:
			configured.append(row)
			clashes.setdefault(prefix, []).append(g["name"])
		else:
			missing.append(row)

	return {
		"configured": configured,
		"missing": sorted(missing, key=lambda r: -r["items"]),
		# Two groups sharing a prefix would share a counter — almost never intended.
		"duplicate_prefixes": {p: g for p, g in clashes.items() if len(g) > 1},
	}
