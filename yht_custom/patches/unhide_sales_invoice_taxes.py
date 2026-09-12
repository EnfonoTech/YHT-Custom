# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Put the Taxes and Charges section back on Sales Invoice, and unblock Customize Form.

Two things the app can only fix by DELETING rows, because `form_layout._hide_fields`
adds and updates Property Setters but never removes one. Dropping a field out of
`HIDE_FIELDS` therefore stops it being re-hidden and leaves it hidden forever.

## 1 — the client reversed item 3

The first client sheet asked for the Taxes and Charges block to be hidden on Sales
Invoice. The client has now asked for it back, and the production numbers say they
are right: **150 of 2,460** submitted invoices carry no tax template at all — the
zero-rated, export and return cases. The original note named that exact trade-off
("if a zero-rated or export invoice is ever needed, someone with the field unhidden
has to raise it"); it turned out to be 150 invoices, not an edge case.

`SALES VAT 15% - KATC` remains `is_default = 1`, so VAT still applies with nobody
touching the picker. This adds a choice; it removes no automation.

`shipping_rule`, `incoterm` and `named_place` stay hidden — used on **0** invoices,
and they were the noise the client wanted gone. `_TAXES_NOISE` holds that list, and
this patch only ever clears `_TAXES_NOW_VISIBLE`.

## 2 — the reason nobody could save Customize Form

`DocType.validate_fields` refuses *"Field Currency in row 37 cannot be hidden and
mandatory without default"* — and it refuses the WHOLE form, so one such field
blocked every unrelated Customize Form change on Sales Invoice, Sales Order,
Delivery Note, Purchase Invoice, Purchase Receipt and Quotation.

We caused it. `currency` and `conversion_rate` ship `reqd = 1` with no default and
`HIDE_FIELDS` hides both on all six. It stayed invisible because our own steps write
Property Setters directly and never go through that validation — it only surfaces
when a human opens the form and presses Update.

`form_layout.setup_hidden_required_defaults` writes the defaults; it is registered in
`PROVISIONING_STEPS`, so `after_migrate` fixes it on every site. This patch only has
to make sure it has run once on a site that is already deployed.

## Re-runnable

Deleting a row that is already gone is a no-op, and the defaults step is idempotent.
"""

import frappe

from yht_custom.form_layout import _TAXES_NOW_VISIBLE, setup_hidden_required_defaults


def execute():
	# `frappe.delete_doc`, not `frappe.db.delete` — `PropertySetter.on_trash` is what
	# runs `frappe.clear_cache(doctype=…)`. Without it the hidden flags stay live in
	# the cached meta until a restart, and the fix reads as a no-op on a running site.
	rows = frappe.get_all(
		"Property Setter",
		filters={
			"doc_type": "Sales Invoice",
			"field_name": ["in", list(_TAXES_NOW_VISIBLE)],
			"property": "hidden",
		},
		pluck="name",
	)
	for name in rows:
		frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)

	defaults = setup_hidden_required_defaults()
	frappe.db.commit()

	print(f"  un-hid {len(rows)} Taxes and Charges row(s) on Sales Invoice")
	for key, value in sorted(defaults.items()):
		print(f"  default set: {key} = {value}")
	if not defaults:
		print("  no hidden+mandatory field needed a default")
