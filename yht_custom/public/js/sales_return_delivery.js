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
// An invoice shipped in several consignments produces a credit note whose lines
// trace back to several delivery notes, and one delivery return can only reverse
// one of them (`return_against` is a single link). So when there is more than one,
// the button asks WHICH shipment is coming back rather than refusing — on khobhar
// that is 11 credit notes covering 97 delivery notes.
//
// The server decides what is offerable; the form only draws the answer.

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
					const label =
						state.pending > 1
							? __("Delivery Note ({0})", [state.pending])
							: __("Delivery Note");
					frm.add_custom_button(label, () => start(frm, state), __("Create"));
				}

				// Point at what already exists rather than offering a duplicate.
				(state.options || [])
					.filter((o) => o.status === "created")
					.forEach((o) =>
						frm.add_custom_button(
							o.existing,
							() => frappe.set_route("Form", "Delivery Note", o.existing),
							__("View")
						)
					);
				if (!state.options?.length && state.existing) {
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

function start(frm, state) {
	const pending = (state.options || []).filter((o) => o.status === "pending");

	// One shipment to bring back: no question worth asking.
	if (pending.length <= 1) {
		build(frm, state.delivery_note || (pending[0] && pending[0].delivery_note));
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Which delivery is coming back?"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "help",
				options: `<p class="text-muted">${__(
					"These lines were delivered on {0} separate delivery notes. One delivery return is raised per delivery note, so pick the one coming back now and repeat for the others.",
					[pending.length]
				)}</p>`,
			},
			{
				fieldname: "delivery_note",
				fieldtype: "Select",
				label: __("Delivery Note"),
				reqd: 1,
				options: pending
					.map((o) => o.delivery_note)
					.join("\n"),
				default: pending[0].delivery_note,
			},
			{
				fieldtype: "HTML",
				fieldname: "detail",
				options: rows_table(pending),
			},
		],
		primary_action_label: __("Create Delivery Return"),
		primary_action(values) {
			dialog.hide();
			build(frm, values.delivery_note);
		},
	});
	dialog.show();
}

function rows_table(pending) {
	const body = pending
		.map(
			(o) =>
				`<tr><td>${frappe.utils.escape_html(o.delivery_note)}</td>` +
				`<td class="text-right">${o.rows}</td>` +
				`<td>${frappe.utils.escape_html((o.idx || []).join(", "))}</td></tr>`
		)
		.join("");
	return `<table class="table table-bordered" style="margin-top:10px">
		<thead><tr>
			<th>${__("Delivery Note")}</th>
			<th class="text-right">${__("Lines")}</th>
			<th>${__("Row numbers on this credit note")}</th>
		</tr></thead><tbody>${body}</tbody></table>`;
}

function build(frm, delivery_note) {
	// make_mapped_doc calls the method with ONE positional argument and puts the
	// rest in frappe.flags.args — the server reads the chosen note from there.
	frappe.model.open_mapped_doc({
		method: "yht_custom.delivery_return.make_delivery_note_from_sales_return",
		frm: frm,
		args: { delivery_note: delivery_note || null },
		freeze_message: __("Building the delivery return…"),
	});
}
