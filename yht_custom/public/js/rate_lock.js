// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Item 5 — a rate fetched from a Sales Order or Delivery Note is not editable.
//
// THIS IS UX, NOT A BOUNDARY. `yht_custom.rate_lock.enforce_fetched_rate` runs on
// validate and is what actually stops an edited rate; it survives
// frappe.client.set_value, a Data Import and a Server Script, none of which load
// this file. Greying the cell just means nobody discovers the rule by having their
// save rejected.
//
// Per-ROW, not per-field: an invoice routinely mixes fetched rows with hand-added
// ones, and locking the whole column would stop an operator adding a line at all.

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		lock_fetched_rates(frm);
	},
	items_add(frm) {
		lock_fetched_rates(frm);
	},
});

function lock_fetched_rates(frm) {
	// A credit note restates the original on purpose, and the server allows it.
	if (frm.doc.is_return) return;

	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (!grid) return;

	(grid.grid_rows || []).forEach((row) => {
		if (!row.doc) return;
		const fetched = Boolean(row.doc.dn_detail || row.doc.so_detail);
		// toggle_editable is the per-row API; set_df_property would hit every row.
		if (row.toggle_editable) row.toggle_editable("rate", !fetched);
	});
}
