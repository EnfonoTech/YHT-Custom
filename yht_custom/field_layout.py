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
FIELD_MOVES = {
	"Sales Invoice": [
		("po_no", "company_tax_id"),
		("po_date", "po_no"),
	],
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


def apply_field_moves() -> dict:
	"""Idempotent. Only ever REORDERS — never adds or drops a fieldname."""
	moved, already, skipped = 0, 0, []

	for doctype, moves in FIELD_MOVES.items():
		if not frappe.db.exists("DocType", doctype):
			skipped.append(f"{doctype}: no such doctype")
			continue

		ps_name, order = _read_order(doctype)
		original = list(order)

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
