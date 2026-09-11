# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Withdraw item 24: delete the `title_field = "name"` Property Setters.

🔴 REMOVING THE PROVISIONING STEP IS ONLY HALF THE REPAIR. A Property Setter
persists, so a site that has already migrated the branch that carried
`setup_title_as_voucher_no` keeps eight broken list views forever, and no amount
of not-writing-the-row again fixes one that is already there.

What it broke, verified upstream and then measured:
`frappe/public/js/frappe/list/list_view.js` builds the subject column as
`df: get_df(this.meta.title_field)` where `get_df` is `frappe.meta.get_docfield`.
`name` is the primary key and has no DocField row, so that resolves to
`undefined`, `get_header_html` dereferences `.fieldname` on it and throws, and the
list renders ZERO rows. Measured on `yht-test` 2026-09-10: `/app/item` 20 rows,
`/app/customer` 8 rows, and all eight of `form_layout.TITLE_AS_VOUCHER_NO` 0 rows
with `TypeError: Cannot read properties of undefined (reading 'fieldname')`.

Deleting the row is the whole fix and it needs no replacement: with no
`title_field` Property Setter, `frappe/model/meta.py::get_title_field` returns the
shipped value, which is a real DocField on every one of the eight, and
`list_view.js`'s own `else` branch already labels the subject column "ID" and
reads `name` for a doctype that sets none — i.e. what item 24 asked for is close
to what frappe does by default, and asking for it explicitly is what broke.

Scoped twice over, because a Property Setter this patch did not write is not this
patch's to delete: only the eight doctypes item 24 named, and only where the value
is literally `name`. A `title_field` an implementer set to a real field through
Customize Form is left exactly as it is.

Item 24 itself is NOT delivered by this branch. `form_layout.setup_title_as_voucher_no`
is left in place, unregistered, so whatever mechanism replaces it can be written
against the same constant — see `.pipeline/changes.md`, "Spec Issues".
"""

import frappe

from yht_custom.form_layout import TITLE_AS_VOUCHER_NO


def execute():
	deleted = []

	for doctype in TITLE_AS_VOUCHER_NO:
		for row in frappe.get_all(
			"Property Setter",
			filters={"doc_type": doctype, "property": "title_field", "value": "name"},
			fields=["name"],
		):
			# `delete_doc` rather than `frappe.db.delete`: `PropertySetter.on_trash`
			# is what runs `frappe.clear_cache(doctype=…)`, and without it the broken
			# meta stays live until the next restart.
			frappe.delete_doc("Property Setter", row.name, ignore_permissions=True)
			deleted.append(row.name)

	if deleted:
		print(f"  item 24 withdrawn — deleted {len(deleted)} title_field Property Setters:")
		for name in deleted:
			print(f"    {name}")

	frappe.db.commit()
