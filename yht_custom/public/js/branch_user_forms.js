// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Branch-user form shaping. Two jobs:
//
//   1. Constrain warehouse and cost-center pickers to the user's branch. This is
//      UX ONLY — yht_custom.branch_guard.validate_branch_scope is what actually
//      enforces it, server-side, on every write path. Never treat this file as a
//      security boundary.
//   2. Hide the cost centre from branch users (MoM 2.5: "Cost centre hidden and
//      derived automatically from branch"). Done here rather than with a Property
//      Setter because a Property Setter would hide it from accountants too.

frappe.provide("yht_custom.branch");

// Cached per page load — the scope cannot change mid-session.
yht_custom.branch.scope = null;

yht_custom.branch.get_scope = function () {
	if (yht_custom.branch.scope) return Promise.resolve(yht_custom.branch.scope);
	return frappe.call({ method: "yht_custom.branch_guard.get_branch_scope" }).then((r) => {
		yht_custom.branch.scope = r.message || { restricted: false, warehouses: [], cost_centers: [] };
		return yht_custom.branch.scope;
	});
};

const WAREHOUSE_FIELDS = {
	header: ["set_warehouse", "set_from_warehouse", "from_warehouse", "to_warehouse"],
	item: ["warehouse", "target_warehouse", "s_warehouse", "t_warehouse", "from_warehouse"],
};

const DOCTYPES = [
	"Quotation",
	"Sales Order",
	"Delivery Note",
	"Sales Invoice",
	"Purchase Order",
	"Purchase Receipt",
	"Purchase Invoice",
	"Material Request",
	"Stock Entry",
];

DOCTYPES.forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		onload(frm) {
			yht_custom.branch.get_scope().then((scope) => apply(frm, scope));
		},
		refresh(frm) {
			yht_custom.branch.get_scope().then((scope) => apply(frm, scope));
		},
	});
});

function apply(frm, scope) {
	if (!scope || !scope.restricted) return;

	const wh_filter = () => ({ filters: { name: ["in", scope.warehouses] } });
	const cc_filter = () => ({ filters: { name: ["in", scope.cost_centers] } });

	WAREHOUSE_FIELDS.header.forEach((f) => {
		if (frm.fields_dict[f]) frm.set_query(f, wh_filter);
	});

	const grid = frm.fields_dict.items || frm.fields_dict.items_table;
	if (grid) {
		WAREHOUSE_FIELDS.item.forEach((f) => {
			if (frm.get_docfield("items", f)) frm.set_query(f, "items", wh_filter);
		});
		if (frm.get_docfield("items", "cost_center")) frm.set_query("cost_center", "items", cc_filter);
	}
	if (frm.fields_dict.cost_center) frm.set_query("cost_center", cc_filter);

	hide_cost_centre(frm);
}

function hide_cost_centre(frm) {
	// MoM 2.5 — branch users never pick a cost centre; branch_defaults derives it.
	// Only hide for a plain Branch User: anyone carrying an accounting role needs
	// to see and change it.
	const roles = frappe.user_roles || [];
	const privileged = [
		"System Manager",
		"Stock Manager",
		"Accounts Manager",
		"Accounts User",
		"Sales Manager",
		"Sales Master Manager",
	];
	if (privileged.some((r) => roles.includes(r))) return;
	if (!roles.includes("Branch User")) return;

	if (frm.fields_dict.cost_center) frm.set_df_property("cost_center", "hidden", 1);
	if (frm.get_docfield("items", "cost_center")) {
		frm.fields_dict.items.grid.update_docfield_property("cost_center", "hidden", 1);
	}
}
