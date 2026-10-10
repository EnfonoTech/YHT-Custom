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

🔴 BOTH LEVERS, NOT ONE — measured on `yht-test` 2026-10-10, headless, as Administrator.
`list_view.js::setup_columns` builds its candidate columns from the docfields
flagged `in_list_view` (plus a Status *indicator* column when the doctype has
one), and `reorder_listview_fields` then walks `List View Settings.fields` and
keeps the candidates it names — it can REORDER and DROP, it cannot ADD. So a
settings row naming `posting_date` does nothing for a doctype whose
`posting_date` is not `in_list_view`, and the Status column answers only to the
settings entry `{"type": "Status", "fieldname": "status_field"}`, never to the
`status` docfield. The first version of this module wrote the `in_list_view`
setters and worked; the second removed them as "a hidden hack" and left only
the settings row — and the lists rendered Customer Name · Grand Total · ID,
with Date and Status gone, because Grand Total was the one field already
`in_list_view`. That is the state a reviewer then called "not rendering".

`in_list_view` is what Customize Form's own "In List View" tick writes. It
does also feed the link-search preview and the report view, which is accepted:
Date and Grand Total are sensible there too.

`title_field` stays a Property Setter — it is what removes the Title column.
"""

import frappe

from yht_custom import features

#: doctype → (title_field, the default list columns, in order).
#:
#: Four entries and no more: `list_view.js` shows at most four columns beside the
#: subject before it starts dropping them, and the whole complaint is that the
#: customer name had no room.
#: The Status column is the doctype's INDICATOR, not its `status` docfield — see
#: the docstring. It is named by this token in the column tuples.
STATUS_INDICATOR = "status"

LIST_COLUMNS = {
	"Delivery Note": ("customer_name", ("posting_date", STATUS_INDICATOR, "grand_total")),
	"Sales Invoice": ("customer_name", ("posting_date", STATUS_INDICATOR, "grand_total")),
}

#: Kept for the tests that assert the Title column is the one being displaced.
CLEAR_IN_LIST_VIEW = {
	"Delivery Note": ("title",),
	"Sales Invoice": ("title",),
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

		shown = []
		for fieldname in columns:
			if fieldname == STATUS_INDICATOR:
				shown.append(fieldname)
				continue
			if not meta.get_field(fieldname):
				continue
			# Lever one: a field is only a candidate column when it is in_list_view.
			_set_property(doctype, fieldname, "in_list_view", "1", "Check")
			shown.append(fieldname)
		# Lever two: the settings row orders (and caps) the candidates.
		_write_list_view_settings(doctype, shown)

		frappe.clear_cache(doctype=doctype)
		applied[doctype] = {"title_field": title_field, "columns": shown}

	return applied


def _write_list_view_settings(doctype: str, fieldnames: list) -> None:
	"""Store the default columns the way the desk itself stores them.

	`List View Settings` is named after the doctype and its `fields` column is a
	JSON list of `{fieldname, label}`. Compared before writing: this runs inside
	`after_migrate` on every deploy, and rewriting the row each time would flood
	the Version table and reset the list under anyone who has it open.
	"""
	import json

	meta = frappe.get_meta(doctype)
	entries = []
	for f in fieldnames:
		if f == STATUS_INDICATOR:
			# The indicator column, exactly as the desk writes it when a user drags it.
			entries.append({"type": "Status", "label": "Status", "fieldname": "status_field"})
		else:
			entries.append({"fieldname": f, "label": meta.get_label(f) or f})
	wanted = json.dumps(entries)

	if frappe.db.exists("List View Settings", doctype):
		if frappe.db.get_value("List View Settings", doctype, "fields") != wanted:
			frappe.db.set_value("List View Settings", doctype, "fields", wanted)
		return

	frappe.get_doc(
		{"doctype": "List View Settings", "name": doctype, "fields": wanted}
	).insert(ignore_permissions=True)


def drop_stale_in_list_view_setters() -> dict:
	"""Undo the first version of this module.

	It wrote `in_list_view` Property Setters on each DocField. Those outlive a code
	change — a Property Setter is a row, not a line of code — so the wrong
	mechanism keeps working until something deletes it, and the list would then be
	driven by two mechanisms that disagree.

	Only the rows the FIRST version could have written are touched, minus the
	column fields the current version sets on purpose.
	"""
	touched = []
	for doctype, (_title, columns) in LIST_COLUMNS.items():
		# The column fields are NOT in this set any more: since 2026-10-10 the
		# module writes their `in_list_view` itself (see the docstring), and this
		# runs from a patch that may land on a site AFTER that write.
		names = set(CLEAR_IN_LIST_VIEW.get(doctype, ()))
		names |= {"customer", "set_warehouse", "po_no", "due_date", "outstanding_amount"}
		names -= set(columns)
		for row in frappe.get_all(
			"Property Setter",
			filters={"doc_type": doctype, "property": "in_list_view", "field_name": ["in", list(names)]},
			pluck="name",
		):
			frappe.delete_doc("Property Setter", row, force=1, ignore_permissions=True)
			touched.append(row)
		if touched:
			frappe.clear_cache(doctype=doctype)
	return {"deleted": touched}
