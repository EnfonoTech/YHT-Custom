// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Create > Delivery Note on a submitted SALES RETURN, so the credited stock can be
// brought back after the credit note rather than before it.
//
//     Delivery Note ─► Sales Invoice ─► Sales Return ─► [Create] ─► Delivery Return
//
// Off unless `YHT Return Settings.allow_delivery_note_from_sales_return` is ticked —
// the standing rule is the other way round (raise the return on the Delivery Note),
// so this button must not appear on a site that has not opted in.
//
// The server decides whether it is offerable, because the answer depends on whether
// every row traces back to ONE delivery note, and that is not knowable in the form.

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (!frm.doc.is_return) return;

		frappe.call({
			method: "yht_custom.delivery_return.can_make_delivery_note",
			args: { source_name: frm.doc.name },
			callback(r) {
				const state = r.message || {};
				// Silent when the feature is off — a disabled button on every credit
				// note would be noise on a site that does not use this route.
				if (state.reason === "disabled") return;

				if (state.allowed) {
					frm.add_custom_button(
						__("Delivery Note"),
						() =>
							frappe.model.open_mapped_doc({
								method: "yht_custom.delivery_return.make_delivery_note_from_sales_return",
								frm: frm,
								freeze_message: __("Building the delivery return…"),
							}),
						__("Create")
					);
					return;
				}

				// Already raised — point at it rather than offering a duplicate.
				if (state.existing) {
					frm.add_custom_button(
						__("Delivery Return"),
						() => frappe.set_route("Form", "Delivery Note", state.existing),
						__("View")
					);
				}
			},
		});
	},
});
