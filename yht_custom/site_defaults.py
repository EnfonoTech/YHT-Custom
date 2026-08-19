# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Site defaults that must not drift, and the dangling links that block them.

## Why this exists

The site shipped with `Selling Settings.selling_price_list = "Ecozone selling"`
— a price list carrying **8** of 4,053 item prices — while `Kathoom Selling Price`
carries **2,860**. Every new Sales Invoice therefore opened with a rate of 0.00,
which reads as "pricing is broken" and blocks UAT outright. Same on the buying
side: `Ecozone buying` (9 prices) against `Kathoom Buying Price` (1,868).

Encoded here rather than fixed by hand because the go-live re-import brings the
same source data through the same pipeline and would reintroduce it.

## Two traps this function exists to avoid

1. **`frappe.db.set_single_value` is NOT enough for a Settings doctype.**
   `SellingSettings.validate` does `frappe.db.set_default("selling_price_list", …)`,
   and `erpnext.accounts.party` reads that **default**, not the single value. Writing
   the field alone leaves the field right and the default stale, so documents keep
   picking the old list. The doc must be **saved** so the controller propagates.

2. **A dangling Link makes the Settings doc unsaveable.**
   `Selling Settings.role_to_override_stop_action` pointed at `YH - Admin`, one of
   the 30 junk roles stripped in Step 1, so every `.save()` died with
   `LinkValidationError: Could not find Role Allowed to Override Stop Action`.
   Deleting a role does not clear the fields pointing at it — so those are cleared
   first, or nothing below can run.
"""

import frappe

#: Chosen by coverage at run time, not hardcoded, so the re-import lands on
#: whatever price list actually carries the rates.
MIN_COVERAGE = 50


def setup_site_defaults():
	_clear_dangling_role_links()
	_set_price_list_defaults()


def _clear_dangling_role_links():
	"""Null every Link → Role field whose target no longer exists.

	Runs first: a dangling role link blocks `.save()` on the doctype holding it.
	"""
	cleared = []
	for field in frappe.get_all(
		"DocField", filters={"fieldtype": "Link", "options": "Role"}, fields=["parent", "fieldname"]
	):
		doctype, fieldname = field.parent, field.fieldname
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		if not meta.issingle:
			continue  # non-singles are the operator's data, not ours to rewrite
		value = frappe.db.get_single_value(doctype, fieldname)
		if value and not frappe.db.exists("Role", value):
			frappe.db.set_single_value(doctype, fieldname, None)
			cleared.append(f"{doctype}.{fieldname} (was {value})")

	# Role rows on Pages / Workspaces / Reports pointing at deleted roles.
	for child in ("Has Role",):
		if not frappe.db.exists("DocType", child) or not frappe.db.has_column(child, "role"):
			continue
		for row in frappe.get_all(child, fields=["name", "role"], limit=5000):
			if row.role and not frappe.db.exists("Role", row.role):
				frappe.db.delete(child, {"name": row.name})
				cleared.append(f"{child} row -> {row.role}")

	if cleared:
		frappe.log_error("Cleared dangling role links:\n" + "\n".join(cleared), "YHT site defaults")
	return cleared


def _best_price_list(side: str) -> str | None:
	"""The enabled price list on this side carrying the most rates."""
	rows = frappe.db.sql(
		f"""
		SELECT p.price_list, COUNT(*) AS c
		FROM `tabItem Price` p
		INNER JOIN `tabPrice List` l ON l.name = p.price_list
		WHERE l.`{side}` = 1 AND l.enabled = 1
		GROUP BY p.price_list
		ORDER BY c DESC
		LIMIT 1
		""",
	)
	if not rows or rows[0][1] < MIN_COVERAGE:
		return None
	return rows[0][0]


def _set_price_list_defaults():
	for doctype, fieldname, side in (
		("Selling Settings", "selling_price_list", "selling"),
		("Buying Settings", "buying_price_list", "buying"),
	):
		best = _best_price_list(side)
		if not best:
			continue

		current = frappe.db.get_single_value(doctype, fieldname)
		default = frappe.db.get_default(fieldname)
		if current == best and default == best:
			continue

		# Save through the controller. set_single_value would leave the default
		# stale, and the default is what erpnext.accounts.party actually reads.
		settings = frappe.get_single(doctype)
		settings.set(fieldname, best)
		settings.flags.ignore_permissions = True
		settings.save()
