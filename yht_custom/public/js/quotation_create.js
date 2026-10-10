// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Row 11 (2026-10-08) — Create > Sales Invoice / Delivery Note on a submitted
// Quotation. ERPNext's own quotation.js offers only Sales Order (its line 125)
// even though the server ships `make_sales_invoice`; the Delivery Note mapper is
// ours (`yht_custom.quotation_flow`).
//
// Behind `oct08_r11_quotation_create`: this file is served to BOTH sites from
// one app directory, and `frappe.boot.yht_features` is how a script learns which
// site it is on (see features.py).

function yht_r11_on() {
	return ((frappe.boot && frappe.boot.yht_features) || []).includes("oct08_r11_quotation_create");
}

frappe.ui.form.on("Quotation", {
	refresh(frm) {
		if (!yht_r11_on()) return;
		if (frm.doc.docstatus !== 1 || frm.doc.status === "Lost") return;

		// `refresh` clears custom buttons before any script runs, so adding here
		// cannot stack; the Create group is the one ERPNext already built.
		if (frappe.model.can_create("Sales Invoice")) {
			frm.add_custom_button(
				__("Sales Invoice"),
				() =>
					frappe.model.open_mapped_doc({
						method: "erpnext.selling.doctype.quotation.quotation.make_sales_invoice",
						frm: frm,
					}),
				__("Create")
			);
		}
		if (frappe.model.can_create("Delivery Note")) {
			frm.add_custom_button(
				__("Delivery Note"),
				() =>
					frappe.model.open_mapped_doc({
						method: "yht_custom.quotation_flow.make_delivery_note",
						frm: frm,
					}),
				__("Create")
			);
		}
	},
});
