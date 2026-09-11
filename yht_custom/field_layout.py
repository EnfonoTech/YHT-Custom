# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Reposition STANDARD fields, reproducibly.

A standard field cannot be moved with `insert_after` — that property belongs to
Custom Field. The only lever is the DocType's ``field_order`` Property Setter,
which frappe applies over the shipped order. Doing it here rather than through
Customize Form means the layout is in git, survives a rebuild, and says why.

⚠️ A field takes its tab, section and column from WHERE IT LANDS in the order —
there is no "section" property to set. Moving a field means placing it after the
right anchor and nothing else, and it silently changes tab if the anchor is in a
different one. That is the mechanism, and it is also the trap.
"""

import json
import os

import frappe

#: doctype → [(fieldname, the field it must sit immediately after)].
#:
#: `po_no` / `po_date` ship in More Info → Customer PO Details, three tabs deep at
#: positions 175 and 177, and nothing had ever moved them (zero Property Setters
#: named either field). They are filled on 969 and 795 of 2,353 invoices — 41% and
#: 34% — which is far too often for a field that needs two clicks to reach. They
#: move to the end of the first column of `customer_section`, immediately under
#: the customer block, because that is when an operator types them: pick the
#: customer, then enter the customer's order number.
#:
#: Client sheet item 29 — the Address form, English left and Arabic right.
#: Upstream ships the two-column frame already (`address_details` →
#: `address_title` … `pincode`, then `column_break0` → `email_id` … `disabled`),
#: so only the sequence inside each column moves. The client's left column reads
#:
#:   Short Address · Type · Building No · Street Name · Additional No · District
#:   · Postal Code · City · Country
#:
#: and of those only `address_type`, `address_line1`, `pincode`, `city` and
#: `country` are STANDARD fields, i.e. only they can move through `field_order`.
#: Shipped, `pincode` sits last of the nine and `city` ahead of `country`; three
#: moves put the trio in the client's order. `county` and `state` are not in the
#: client's list and are not dropped — the permutation guard below would refuse
#: that anyway — so they trail the left column.
#:
#: 🔴 `pincode` IS ANCHORED ON `address_line2`, NOT ON `address_line1`, AND THAT
#: IS THE WHOLE OF "SHAPE THE COLUMN AROUND THE FIELDS WE MAY NOT MOVE".
#: `ksa_compliance` ships `custom_building_number` with `insert_after:
#: "address_line2"` and `custom_area` behind it, in a `sync_on_migrate`
#: customization file it re-applies on every migrate (see CUSTOM_FIELD_MOVES), so
#: those two land immediately after `address_line2` whatever we would prefer.
#: Anchoring the postal trio behind `address_line2` therefore puts Building No and
#: District together just ahead of Postal Code · City · Country, which is the
#: closest the client's sequence gets without fighting another installed app:
#:
#:   Short Address · Type · Street Name · Additional No · Unit No ·
#:   Address Line 2 · Building No · District · Postal Code · City · Country
FIELD_MOVES = {
	"Sales Invoice": [
		("po_no", "company_tax_id"),
		("po_date", "po_no"),
	],
	"Address": [
		("pincode", "address_line2"),
		("city", "pincode"),
		("country", "city"),
	],
}

#: doctype → [(CUSTOM fieldname, the field it must sit immediately after)].
#:
#: The complement of FIELD_MOVES: a custom field is positioned by its own
#: `insert_after`, which `frappe/model/meta.py::sort_fields` splices in for every
#: field the `field_order` Property Setter does not already name.
#:
#: 🔴 AND THAT "does not already name" IS LOAD-BEARING. `sort_fields` returns
#: EARLY — `if len(field_order) == len(self.fields): _update_fields_based_on_order
#: (field_order); return` — so once a `field_order` Property Setter lists every
#: field, which is exactly what a Customize Form save writes, `insert_after` is
#: never consulted again. A third developer is hand-editing Address field order
#: through Customize Form, so both levers are driven here: the `insert_after` is
#: written, AND the same pair is replayed through the permutation-guarded
#: reorder for whatever the stored order already carries.
#:
#: Item 29 only NEEDS the four Arabic fields moved — they belong in the right-hand
#: column. Our own three Address custom fields are anchored in
#: `saudi_address.ADDRESS_CUSTOM_FIELDS` instead — `create_custom_fields`
#: re-applies `insert_after` on every migrate, so a second opinion here would be
#: overwritten and then rewritten forever.
#:
#: 🔴 GATE Q8'S STOP CONDITION HAS FIRED, AND `module: NULL` WAS THE WRONG TEST.
#: The gate approved the move on the measurement that all ten Address Custom
#: Fields carry `module: NULL` and are therefore "not fixture-owned". They are
#: not owned through the `fixtures` HOOK — no installed app on this bench uses it
#: for Address — but that is not the mechanism in play. `ksa_compliance` and
#: `arabic_translation` each ship `<app>/<module>/custom/address.json` with
#: `sync_on_migrate: 1`, and `frappe/modules/utils.py::sync_customizations` does
#: `custom_field.update(d); custom_field.db_update()` for every field in the file
#: on EVERY migrate — `insert_after` included, `module` column irrelevant.
#:
#: Measured on `yht-test` 2026-09-10 — ALL SIX fields item 29 wanted to move are
#: re-applied that way, every one of them `module: NULL`:
#:
#:   custom_building_number       ksa_compliance      -> address_line2
#:   custom_area                  ksa_compliance      -> custom_building_number
#:                                arabic_translation  -> address_line2  (wins: later app)
#:   custom_address_line1_arabic  arabic_translation  -> address_line1
#:   custom_area_arabic           arabic_translation  -> custom_area
#:   custom_city_arabic           arabic_translation  -> city
#:   custom_country_arabic        arabic_translation  -> country
#:
#: So the list is EMPTY, per the gate's own "stop and report rather than move it".
#: `FIELD_MOVES["Address"]` is shaped around where those six actually land; the
#: two `ksa_compliance` fields end up together just ahead of Postal Code, which
#: is the closest the client's left column gets.
#:
#: 🔴 WHAT THAT COSTS, STATED: item 29's Arabic RIGHT-HAND COLUMN is not
#: delivered. `arabic_translation` anchors all four Arabic fields beside their
#: English twins, i.e. in the LEFT column, and `insert_after` is the only lever
#: this module has. The one mechanism that would win is a `field_order` Property
#: Setter naming EVERY field including the custom ones — `sort_fields` returns
#: early on `len(field_order) == len(self.fields)` and never consults
#: `insert_after` again — but that is a different design from the one this module
#: is built on, and choosing it is a spec decision rather than a coder's. See
#: `.pipeline/changes.md`, "Spec Issues". The dict and the guard stay so the next
#: entry is checked the same way.
CUSTOM_FIELD_MOVES = {
	"Address": [],
}


def _read_order(doctype: str):
	"""``(property_setter_name_or_None, field_order_list)``."""
	ps = frappe.db.get_value(
		"Property Setter",
		{"doc_type": doctype, "property": "field_order", "doctype_or_field": "DocType"},
		["name", "value"],
		as_dict=True,
	)
	if ps and ps.value:
		try:
			order = json.loads(ps.value)
			if isinstance(order, list) and order:
				return ps.name, order
		except (ValueError, TypeError):
			pass

	# No usable setter yet. Seed from the shipped order — standard fields only,
	# because a Custom Field is positioned by its own `insert_after` and listing it
	# here would fight that.
	meta = frappe.get_meta(doctype)
	order = [f.fieldname for f in meta.fields if not f.get("is_custom_field")]
	return (ps.name if ps else None), order


def app_owned_custom_fields(doctype: str) -> set:
	"""Every `doctype` Custom Field an installed app re-applies on its own migrate.

	🔴 THE `module` COLUMN IS NOT THE OWNERSHIP TEST, AND NEITHER IS THE `fixtures`
	HOOK ON ITS OWN. Two mechanisms put a Custom Field back the way its app wants
	it, and on this bench only the second is in use:

	* the **`fixtures` hook** — `{"dt": "Custom Field", "filters": [["name", "in",
	  [...]]]}`, exported and re-imported by `bench migrate`. Both shapes a filter
	  list carries are read here: the record name (`Address-custom_area`) and a
	  bare fieldname.
	* **`<app>/<module>/custom/<doctype>.json` with `sync_on_migrate` truthy** —
	  `frappe/modules/utils.py::sync_customizations` walks exactly that path for
	  every installed app on every migrate and, when the field already exists,
	  runs `custom_field.update(d); custom_field.db_update()`. Every key in the
	  file is re-applied, `insert_after` INCLUDED, and the field's `module` column
	  is never consulted. This is how `ksa_compliance` and `arabic_translation`
	  own the six Address fields gate Q8 asked about, all of them `module: NULL`.

	Both mechanisms are read for EVERY installed app, this one included: our own
	three Address fields come back as owned via `hooks.fixtures`, which is
	correct — `saudi_address.ADDRESS_CUSTOM_FIELDS` re-applies their
	`insert_after` on every migrate, so a second opinion here would lose too.

	The walk mirrors `sync_customizations` deliberately — installed apps only,
	`frappe.local.app_modules` for the module folders, the file's own `doctype`
	key rather than its filename — so what this reports is what will actually be
	re-applied. A file that cannot be read is skipped rather than raised: this
	runs inside `after_migrate`, and a malformed JSON in someone else's app must
	not take the layout step down with it.
	"""
	owned = set()
	prefix = f"{doctype}-"

	for app in frappe.get_installed_apps():
		for entry in frappe.get_hooks("fixtures", app_name=app) or []:
			if not isinstance(entry, dict) or entry.get("dt") != "Custom Field":
				continue
			for clause in entry.get("filters") or []:
				if len(clause) != 3 or clause[1] != "in":
					continue
				for value in clause[2] or []:
					value = str(value)
					owned.add(value[len(prefix) :] if value.startswith(prefix) else value)

		for module in (frappe.local.app_modules or {}).get(app) or []:
			folder = frappe.get_app_path(app, module, "custom")
			if not os.path.isdir(folder):
				continue
			for filename in os.listdir(folder):
				if not filename.endswith(".json"):
					continue
				try:
					with open(os.path.join(folder, filename), encoding="utf-8") as handle:
						data = json.loads(handle.read())
				except (OSError, ValueError):
					continue
				if not data.get("sync_on_migrate") or data.get("doctype") != doctype:
					continue
				for field in data.get("custom_fields") or []:
					if field.get("fieldname"):
						owned.add(field["fieldname"])

	return owned


def _apply_custom_field_moves(skipped: list) -> int:
	"""Re-anchor a CUSTOM field by rewriting its own `insert_after`.

	`frappe.db.set_value` rather than a document save: `CustomField.validate`
	would reject an anchor it cannot see in its own idea of the meta, and the
	only thing that has to change is one column. The doctype cache is cleared
	once per doctype afterwards, or the new order is invisible until the next
	restart.
	"""
	written = 0

	for doctype, moves in CUSTOM_FIELD_MOVES.items():
		if not frappe.db.exists("DocType", doctype):
			continue

		meta = frappe.get_meta(doctype)
		owned = app_owned_custom_fields(doctype)
		touched = False

		for fieldname, anchor in moves:
			row = frappe.db.get_value(
				"Custom Field",
				{"dt": doctype, "fieldname": fieldname},
				["name", "insert_after", "module"],
				as_dict=True,
			)
			# Not on this site at all — another app's field, another app's install.
			if not row:
				continue
			if row.module:
				# Fixture-owned: whatever we write comes straight back on that app's
				# next migrate, so writing it would be a silent, repeating fight.
				skipped.append(f"{doctype}: {fieldname} belongs to module {row.module}")
				continue
			if fieldname in owned:
				# Same fight, different mechanism — and this is the one that is
				# actually live here. See `app_owned_custom_fields`: a
				# `sync_on_migrate` customization file re-applies `insert_after`
				# whatever the `module` column says. Gate Q8's stop condition:
				# report it, do not move it.
				skipped.append(
					f"{doctype}: {fieldname} is re-applied by an installed app "
					"(fixtures hook or custom/*.json with sync_on_migrate) — not moved"
				)
				continue
			if not meta.get_field(anchor):
				skipped.append(f"{doctype}: {fieldname} anchor {anchor} does not exist")
				continue
			if row.insert_after == anchor:
				continue

			frappe.db.set_value("Custom Field", row.name, "insert_after", anchor)
			written += 1
			touched = True

		if touched:
			frappe.clear_cache(doctype=doctype)

	return written


def apply_field_moves() -> dict:
	"""Idempotent. Only ever REORDERS — never adds or drops a fieldname."""
	moved, already, skipped = 0, 0, []

	moved += _apply_custom_field_moves(skipped)

	for doctype, moves in FIELD_MOVES.items():
		if not frappe.db.exists("DocType", doctype):
			skipped.append(f"{doctype}: no such doctype")
			continue

		ps_name, order = _read_order(doctype)
		original = list(order)

		# Custom fields are normally placed by `insert_after` and are therefore
		# absent from a seeded (standard-only) order — those pairs are filtered out
		# here rather than logged, or a settled site would report a skip on every
		# migrate. They are replayed only for a stored order that already names
		# them, which is the Customize Form case CUSTOM_FIELD_MOVES describes.
		# BOTH ends, not just the field: a stored order written before one of the
		# anchors existed names the field and not its anchor, and reporting that as
		# a skip on every single migrate is worse than leaving the pair to
		# `_apply_custom_field_moves`, which is where a genuinely unresolvable
		# anchor is already logged once.
		moves = list(moves) + [
			pair
			for pair in CUSTOM_FIELD_MOVES.get(doctype, [])
			if pair[0] in order and pair[1] in order
		]

		for fieldname, anchor in moves:
			if fieldname not in order or anchor not in order:
				skipped.append(f"{doctype}: {fieldname} or {anchor} not in field order")
				continue
			if order.index(fieldname) == order.index(anchor) + 1:
				already += 1
				continue
			order.remove(fieldname)
			order.insert(order.index(anchor) + 1, fieldname)
			moved += 1

		if order == original:
			continue

		# The list must be a permutation of what it started as: a dropped fieldname
		# removes the field from the form entirely.
		if sorted(order) != sorted(original):
			skipped.append(f"{doctype}: refusing to write a field_order that is not a permutation")
			continue

		value = json.dumps(order)
		if ps_name:
			frappe.db.set_value("Property Setter", ps_name, "value", value)
		else:
			frappe.get_doc(
				{
					"doctype": "Property Setter",
					"doctype_or_field": "DocType",
					"doc_type": doctype,
					"property": "field_order",
					"property_type": "Text",
					"value": value,
				}
			).insert(ignore_permissions=True)
		frappe.clear_cache(doctype=doctype)

	if skipped:
		frappe.log_error(message="\n".join(skipped), title="yht_custom: field moves")

	return {"moved": moved, "already": already, "skipped": skipped}
