# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""CR-013 — the transaction list, laid out the way the incumbent laid it out.

Client's words: "customer name is not fully visible… no need for the title". The
asked-for columns are ID, Date, Customer Name, Status.

## 🔴 `title_field = "name"` IS THE ONE THING THIS MUST NOT DO

It was tried, on this site, and it rendered all eight transaction lists **empty**:
`list_view.js` resolves the subject column through
`frappe.meta.get_docfield(title_field)`, and `name` is the primary key, not a
DocField, so the lookup returns undefined and the render throws. Measured on
`yht-test`: 0 rows on all eight, TypeError in the console. `setup_title_as_voucher_no`
still exists in `form_layout` and is deliberately NOT registered;
`patches/drop_title_as_voucher_no.py` deleted the rows it had written.

`customer_name` IS a real DocField on both doctypes, which is what makes this
version safe where that one was not — and it is also what the client actually
asked for, because Frappe renders the subject as the title with the document ID
beside it. One wide column carrying both, then Date and Status.

## ⚠️ THE DOCTYPES ARE A GUESS, AND THE SWITCH IS WHY THAT IS ALLOWED

OQ-9 is open: the transcript never names which list. Delivery Note and Sales
Invoice are the two the complaint fits — they are the lists with a `title` field
distinct from the customer, and the two the client works in daily — but that is
inference, not an answer. So the whole step sits behind `cr_013_list_columns`,
which is off on the live site: UAT shows the client what it looks like, and
nothing changes for them until they say which lists they meant.

A list column is per-user once the user has touched it; this only changes the
DEFAULT, which is what a user who has never dragged a column sees.
"""

import frappe

from yht_custom import features

#: doctype → (title_field, the fields that carry `in_list_view`, in order).
#:
#: Four entries and no more: `list_view.js` shows at most four columns beside the
#: subject before it starts dropping them, and the whole complaint is that the
#: customer name had no room.
LIST_COLUMNS = {
	"Delivery Note": ("customer_name", ("posting_date", "status", "grand_total")),
	"Sales Invoice": ("customer_name", ("posting_date", "status", "grand_total")),
}

#: Fields that carry `in_list_view` today and would compete for the same room.
#: Cleared rather than left, because a column the client did not ask for is
#: exactly what pushed the customer name out.
CLEAR_IN_LIST_VIEW = {
	"Delivery Note": ("title", "customer", "set_warehouse", "po_no"),
	"Sales Invoice": ("title", "customer", "due_date", "po_no", "outstanding_amount"),
}


def setup_list_columns() -> dict:
	"""Idempotent. Behind `cr_013_list_columns` — see the module docstring."""
	if not features.enabled("cr_013_list_columns"):
		return {"skipped": "cr_013_list_columns is off for this site"}

	from yht_custom.form_layout import _set_property

	applied = {}
	for doctype, (title_field, columns) in LIST_COLUMNS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)

		# Guard the exact failure the docstring records: a title_field that is not
		# a DocField empties the list.
		if not meta.get_field(title_field):
			frappe.log_error(
				message=f"{doctype}: {title_field} is not a DocField — refusing to set title_field",
				title="yht_custom: list columns",
			)
			continue
		_set_property(doctype, None, "title_field", title_field, "Data", for_doctype=True)

		for fieldname in CLEAR_IN_LIST_VIEW.get(doctype, ()):
			if meta.get_field(fieldname):
				_set_property(doctype, fieldname, "in_list_view", "0", "Check")

		shown = []
		for fieldname in columns:
			if meta.get_field(fieldname):
				_set_property(doctype, fieldname, "in_list_view", "1", "Check")
				shown.append(fieldname)

		frappe.clear_cache(doctype=doctype)
		applied[doctype] = {"title_field": title_field, "columns": shown}

	return applied
