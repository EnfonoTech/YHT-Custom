// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

// CR-006, acceptance criterion #2 — "confirm the warehouse PICKER is scoped to the
// branch, not just the saved value."
//
// 🔴 THE SERVER HANDLER ALONE DOES NOT MEET THIS. `branch_defaults.apply_branch_warehouse`
// corrects the warehouse on `before_validate`, i.e. AFTER the operator has already
// picked one. Without this file the dropdown still lists every warehouse on the
// site, the operator chooses one, and the form silently replaces it on save — which
// reads as the system fighting them rather than as a rule.
//
// The list comes from `frappe.boot.yht_branch_warehouses` (see `boot.py`) because
// `set_query` is registered while the form is being built and has no moment to
// fetch. An EMPTY list means "do not filter": a bypass user, or a user on no
// branch, keeps the full picker — the same "do not guess which branch they meant"
// rule `branch_defaults._branch_series_rows` follows on the server.
//
// Both ends are filtered: the header `set_warehouse` and the item row `warehouse`,
// because the row is what reaches the Stock Ledger.

frappe.provide("yht");

yht.branch_warehouse = {
	list() {
		return (frappe.boot && frappe.boot.yht_branch_warehouses) || [];
	},

	filter() {
		return { filters: { name: ["in", yht.branch_warehouse.list()] } };
	},

	apply(frm) {
		if (!yht.branch_warehouse.list().length) return;

		if (frm.fields_dict.set_warehouse) {
			frm.set_query("set_warehouse", yht.branch_warehouse.filter);
		}
		if (frm.fields_dict.items) {
			frm.set_query("warehouse", "items", yht.branch_warehouse.filter);
		}
	},
};

["Sales Invoice", "Purchase Invoice", "Delivery Note", "Purchase Receipt", "Sales Order", "Quotation"].forEach(
	(doctype) => {
		frappe.ui.form.on(doctype, {
			onload(frm) {
				yht.branch_warehouse.apply(frm);
			},
		});
	}
);
