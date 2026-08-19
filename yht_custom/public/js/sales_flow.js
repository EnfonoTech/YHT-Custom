// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Delivery-Note-compulsory flow, form side.
//
// The lock here is convenience. yht_custom.sales_flow enforces the same rule on
// before_validate, so a REST call or an import cannot route around it.

frappe.provide("yht_custom.flow");

yht_custom.flow.may_direct = null;

yht_custom.flow.check = function () {
	if (yht_custom.flow.may_direct !== null) return Promise.resolve(yht_custom.flow.may_direct);
	return frappe.call({ method: "yht_custom.sales_flow.may_use_direct_stock" }).then((r) => {
		yht_custom.flow.may_direct = !!r.message;
		return yht_custom.flow.may_direct;
	});
};

frappe.ui.form.on("Sales Invoice", {
	onload(frm) {
		apply_si(frm);
	},
	refresh(frm) {
		apply_si(frm);
	},
});

function apply_si(frm) {
	yht_custom.flow.check().then((may_direct) => {
		if (may_direct) return;

		if (frm.is_new()) frm.set_value("update_stock", 0);
		frm.set_df_property("update_stock", "read_only", 1);
		frm.set_df_property(
			"update_stock",
			"description",
			__("Stock is delivered on a Delivery Note. Create the Delivery Note first, then bill it.")
		);

		if (frm.is_new() && !frm.doc.items?.length) {
			frm.dashboard.add_comment(
				__("Bill an existing Delivery Note: use <b>Get Items From → Delivery Note</b>."),
				"blue",
				true
			);
		}
	});
}

frappe.ui.form.on("Delivery Note", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		yht_custom.flow.check().then((may_direct) => {
			if (may_direct) return;
			// Submitted DNs are locked server-side; say so rather than letting the
			// user discover it by having a save rejected.
			frm.dashboard.add_comment(
				__("This Delivery Note is submitted and locked. Raise a return to correct it."),
				"orange",
				true
			);
		});
	},
});
