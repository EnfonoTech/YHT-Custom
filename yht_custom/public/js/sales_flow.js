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


// ------------------------------------------------------- new sales return
//
// 🔴 A SHORTCUT CANNOT TICK `is_return`, AND NEITHER CAN A URL.
//
// `Sales Invoice.is_return` is `no_copy = 1`, and `create_new.js` skips every no_copy
// field when it applies `frappe.route_options`:
//
//     if (df && !df.no_copy) doc[fieldname] = value;
//
// Measured on the site, all three obvious routes come back with is_return = 0:
//   · /app/sales-invoice/new?is_return=1   — frappe also STRIPS the query string, so a
//     client script cannot recover it either
//   · the same with a #hash                — stripped as well
//   · frappe.new_doc("Sales Invoice", { is_return: 1 })
//
// Only setting it AFTER the form exists works. Hence this helper: everything that
// offers a "Sales Return" entry point routes through it.
//
// Ticking it is what earns the separate entry point — `branch_defaults` picks the
// naming series from `is_return` at before_insert, so a BRANCH USER's document numbers
// KSCN- (credit note) instead of KSIN-, which is the whole reason an accountant wants
// the two apart. A user holding a bypass role (System Manager, Accounts Manager, Sales
// Manager, …) is exempt from that override by design and keeps whatever the picker
// shows, so the alert below does not promise a series.

frappe.provide("yht_custom.sales");

yht_custom.sales.new_return = async function () {
	await frappe.new_doc("Sales Invoice");
	// new_doc resolves before the form has finished rendering; set_value on a form that
	// is still building silently loses the value.
	await frappe.after_ajax(() => {});
	if (!cur_frm || cur_frm.doc.doctype !== "Sales Invoice") return;
	await cur_frm.set_value("is_return", 1);
	frappe.show_alert({
		message: __("Return ticked — this is a credit note. Pick the invoice it is against."),
		indicator: "blue",
	});
};

// The same entry point from the Sales Invoice list, so a workspace shortcut to the
// returns list lands one click away from creating one. A Workspace Shortcut is config
// only — it cannot run this — which is why the list carries the button instead.
//
// 🔴 DO NOT MERGE INTO `frappe.listview_settings["Sales Invoice"]`. erpnext's own
// `sales_invoice_list.js` opens with a WHOLESALE ASSIGNMENT to that key, and a doctype's
// list bundle is fetched when the list is first opened — i.e. AFTER `app_include_js`.
// Whatever we merge in at boot is discarded, silently: the button simply never appears,
// with no error. Attach from the router instead, which runs after the view is built no
// matter which file loaded first.
frappe.router.on("change", () => {
	const route = frappe.get_route() || [];
	if (route[0] !== "List" || route[1] !== "Sales Invoice") return;

	// The bundle may still be in flight on a first visit, so poll rather than assume.
	let tries = 0;
	const attach = () => {
		const lv = window.cur_list;
		if (!lv || lv.doctype !== "Sales Invoice" || !lv.page) {
			if (++tries < 20) setTimeout(attach, 150);
			return;
		}
		if (lv.__yht_return_btn) return;
		lv.__yht_return_btn = true;
		lv.page.add_inner_button(__("New Return"), () => yht_custom.sales.new_return());
	};
	attach();
});
