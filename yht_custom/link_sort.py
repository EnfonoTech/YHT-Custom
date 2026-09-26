# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Ordering of link-field search results (client meeting 2026-09-23, CR-016/017).

The client asked for the Customer picker to be ordered by NAME rather than by the
customer code, and said the Item picker was already fine and should be left alone.

🔴 THE LEVER IS THE DOCTYPE'S `sort_field` / `sort_order`, NOT `search_fields`.
`frappe/desk/search.py:183-185` builds the link query's ordering as

    order_by = f"`tab{doctype}`.idx desc, {get_order_by(doctype, meta)}"

and `frappe/model/db_query.py:get_order_by` reads `meta.sort_field` and
`meta.sort_order`, defaulting to `modified desc` when `sort_field` is empty. So a
Property Setter on the DocType is what moves it. `search_fields` only decides
which columns are SEARCHED and displayed, never the order.

⚠️ This also changes the doctype's default LIST view order, because both read the
same two properties. That is a wider change than the client literally asked for,
and it is accepted deliberately: a Customer list ordered by name is the same
improvement for the same reason, and there is no separate lever for the picker.

⚠️ **ITEM IS DELIBERATELY NOT TOUCHED (CR-017).** The client believed Items are
already sorted ascending by code and asked only that we confirm it. Measured on
the live site, that belief is WRONG: `Item.sort_field` is empty, so the ordering
falls through to `modified desc` — what makes it *feel* code-ordered is the
relevance clause `search.py:194` applies once you start typing. Changing it was
not requested, so it stays; the finding goes back to the client instead.
`tests/test_link_sort.py` asserts we leave it alone.
"""

import frappe

#: doctype -> (sort_field, sort_order). Only what the client asked for.
LINK_SORT: dict[str, tuple[str, str]] = {
	"Customer": ("customer_name", "ASC"),
}

#: Asserted by the test suite to stay ABSENT from LINK_SORT — see CR-017 above.
DELIBERATELY_UNSORTED = ("Item",)


def setup_link_sort_order() -> dict[str, str]:
	"""Point the listed doctypes' pickers at a human-readable sort. Idempotent."""
	applied: dict[str, str] = {}

	for doctype, (sort_field, sort_order) in LINK_SORT.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		if not meta.get_field(sort_field):
			# Never write a sort against a field that does not exist: every list
			# and every picker for the doctype would raise on an unknown column.
			frappe.log_error(
				message=f"{doctype}.{sort_field} does not exist; link sort not applied",
				title="YHT link sort",
			)
			continue

		for prop, value in (("sort_field", sort_field), ("sort_order", sort_order)):
			# `frappe.make_property_setter` takes an args DICT (gotcha 16).
			frappe.make_property_setter(
				{
					"doctype": doctype,
					"doctype_or_field": "DocType",
					"property": prop,
					"value": value,
					"property_type": "Data",
				},
				is_system_generated=False,
			)
		frappe.clear_cache(doctype=doctype)
		applied[doctype] = f"{sort_field} {sort_order}"

	return applied
