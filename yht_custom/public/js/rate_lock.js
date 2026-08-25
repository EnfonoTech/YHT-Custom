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
//
// NOTE FOR TESTING: the SERVER refuses an edited fetched rate only for users
// without a bypass role (`sales_flow.DIRECT_STOCK_ROLES` — System/Stock/Sales/
// Sales Master/Accounts Manager). `uat@kathoomcompany.com` holds three of them,
// so the rule looks broken when tested with that account. Test as a Branch User.

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

		// 🔴 NOT `row.toggle_editable("rate", …)`, WHICH IS A SILENT NO-OP HERE.
		// It routes to grid_row.set_field_property, which writes into
		// `grid_form.fields_dict` and `on_grid_fields_dict` and returns early on
		// `if (!field) return;`. A grid row builds those lazily — on a form just
		// loaded from the server BOTH are empty, so the call did nothing and the
		// cell stayed editable. Measured on a draft invoice made from
		// KSSO-26-0625: so_detail set on every row, read_only 0 on every row,
		// and calling toggle_editable by hand changed nothing.
		//
		// `frm.set_df_property` with the six-argument form resolves a PER-ROW
		// docfield through `frappe.meta.get_docfield(parent, field, row_name)`
		// and refreshes just that cell, so it works before the row is opened and
		// does not leak into the other rows.
		frm.set_df_property("items", "read_only", fetched ? 1 : 0, frm.doc.name, "rate", row.doc.name);
	});
}
