# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Remove the `custom_attention` Custom Fields that were created over legacy data.

🔴 WHAT WENT WRONG, 2026-09-26. CR-011 asked for an `Attention` field. It shipped
as `custom_attention`, after checking `tabCustom Field` and finding nothing by
that name. That check was insufficient: `custom_attention` is a LEGACY ORPHAN
COLUMN on FIVE tables — Quotation, Sales Order, Sales Invoice, Delivery Note and
Purchase Order — left behind when the incumbent's field was purged. Gotcha 22:
deleting a Custom Field drops neither the column nor its data.

On Quotation that column still holds **71 rows of real client text**, up to 547
characters, and it is not a contact name — it carries delivery terms such as
*"Delivery: 4-6 working weeks from the date of receipt of P.O"*.

Two consequences, both reached the client's production site:

1. `create_custom_fields` tried to ALTER Quotation's `text` column down to
   `varchar(140)`. **MySQL refused** — *"Data too long for column
   'custom_attention' at row 2823"* — and that refusal is the only reason the 71
   rows survived. The `after_migrate` step failed loudly, which is what surfaced
   this at all.
2. The quotation print rendered that legacy paragraph under an **"Attention:"**
   label on a customer-facing document.

The field is now `custom_attention_person`, which is free on every table. This
patch removes the mis-named Custom Fields so the legacy column goes back to being
invisible — **it deliberately does NOT touch the column or its data**, which is
the client's and is not ours to delete. Reading it needs a decision from them:
those 71 values look like they belong in `terms`.

Re-runnable: deleting a row that is already gone is a no-op.
"""

import frappe

DOCTYPES = ("Quotation", "Sales Order", "Sales Invoice", "Delivery Note")
LEGACY_FIELDNAME = "custom_attention"


def execute():
	removed = []
	for doctype in DOCTYPES:
		name = frappe.db.get_value(
			"Custom Field", {"dt": doctype, "fieldname": LEGACY_FIELDNAME}, "name"
		)
		if not name:
			continue
		# `frappe.delete_doc`, not `frappe.db.delete` — CustomField.on_trash is what
		# clears the cached meta; without it the field stays live on a running site.
		frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
		removed.append(doctype)

	frappe.db.commit()

	for doctype in DOCTYPES:
		frappe.clear_cache(doctype=doctype)

	print(f"  removed the mis-named Attention field from: {removed or 'nothing — already clean'}")
	print("  the legacy `custom_attention` COLUMN and its data are deliberately untouched")
