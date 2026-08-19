// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Price Assist — "what should I charge for this line?" plus the rate history
// behind it.
//
// BUTTON PLACEMENT — read this before moving them again.
//
// Both buttons sit in the ITEM GRID FOOTER, next to Add Row / Add Multiple, which
// is where RMAX and sf_trading put theirs and where operators look for them.
// They are added with frappe's own documented grid API:
//
//     frm.fields_dict.items.grid.add_custom_button(label, fn)   // frappe grid.js
//
// which prepends into `this.grid_buttons` — the very container holding Add Row.
// No DOM search, no fallback selectors.
//
// An earlier revision of this file put Price Assist in the `Tools` dropdown and
// left the history behind a button INSIDE the dialog, on the stated grounds that a
// grid button "is still DOM-dependent". That was wrong — the API above is public
// and stable — and the cost was real: operators could not find either feature.
// sf_trading's last_selling_rate.js hunts four fallback selectors precisely
// because it never used this API. Do not copy that; do not go back to `Tools`.
//
// The one thing to remember: grid.clear_custom_buttons() runs on every grid
// refresh and HIDES custom buttons (adds `.hidden`). Re-calling add_custom_button
// with the same label un-hides the existing button, so both are wired from the
// form's own `refresh` — cheap, and it survives every re-render.

frappe.provide("yht_custom.price");

const SELLING = ["Sales Invoice", "Sales Order", "Delivery Note", "Quotation"];

SELLING.forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		refresh(frm) {
			add_grid_buttons(frm);
		},
		items_add(frm) {
			// A first row can be added before the grid has ever rendered its footer.
			add_grid_buttons(frm);
		},
	});
});

function add_grid_buttons(frm) {
	if (frm.doc.docstatus !== 0) return;
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (!grid || !grid.add_custom_button) return;

	grid.add_custom_button(__("Price Assist"), () => yht_custom.price.open(frm));
	grid.add_custom_button(__("Show Price History"), () => yht_custom.price.open_history(frm));
}

// Opening it from a rate field is the natural gesture, so wire the item table too.
frappe.ui.form.on("Sales Invoice Item", {
	rate(frm, cdt, cdn) {
		yht_custom.price.hint(frm, locals[cdt][cdn]);
	},
});

yht_custom.price.current_row = function (frm) {
	const open = frappe.ui.form.get_open_grid_form();
	if (open && open.doc && open.doc.item_code) return open.doc;
	const rows = (frm.doc.items || []).filter((r) => r.item_code);
	return rows.length ? rows[rows.length - 1] : null;
};

yht_custom.price.open = function (frm) {
	const row = yht_custom.price.current_row(frm);
	if (!row) {
		frappe.msgprint(__("Add an item row first."));
		return;
	}

	frappe.call({
		method: "yht_custom.api.price_assist.get_price_assist",
		args: {
			item_code: row.item_code,
			customer: frm.doc.customer || null,
			company: frm.doc.company,
			price_list: frm.doc.selling_price_list,
			qty: row.qty || 1,
		},
		freeze: true,
		freeze_message: __("Checking prices…"),
		callback(r) {
			if (r.message) yht_custom.price.show(frm, row, r.message);
		},
	});
};

yht_custom.price.show = function (frm, row, d) {
	const money = (v) => (v === null || v === undefined ? "—" : format_currency(v, d.currency));
	const cur = flt(row.rate);
	const val = flt(d.valuation_rate);
	const margin = val && cur ? (((cur - val) / cur) * 100).toFixed(1) : null;

	const line = (label, value, note) =>
		`<tr><td class="text-muted" style="width:38%">${label}</td>
		     <td><b>${value}</b>${note ? ` <span class="text-muted">${note}</span>` : ""}</td></tr>`;

	const mine = d.last_to_this_customer;
	const anyone = d.last_to_anyone;

	let rows = "";
	rows += line(__("Price list rate"), money(d.price_list_rate), d.price_list ? `(${frappe.utils.escape_html(d.price_list)})` : "");
	rows += line(
		__("Last rate to this customer"),
		mine ? money(mine.rate) : __("never sold to them"),
		mine ? `${frappe.datetime.str_to_user(mine.posting_date)} · ${frappe.utils.escape_html(mine.invoice)}` : ""
	);
	rows += line(
		__("Last rate to anyone"),
		anyone ? money(anyone.rate) : __("no sales yet"),
		anyone ? `${frappe.datetime.str_to_user(anyone.posting_date)} · ${frappe.utils.escape_html(anyone.customer_name || anyone.customer)}` : ""
	);
	if (d.band) {
		rows += line(
			__("Recent range"),
			`${money(d.band.low)} – ${money(d.band.high)}`,
			__("avg {0} over {1} sales", [money(d.band.avg), d.band.samples])
		);
	}
	rows += line(__("Valuation"), money(d.valuation_rate));
	if (margin !== null) {
		const colour = margin < 0 ? "red" : margin < 5 ? "orange" : "green";
		rows += line(
			__("Margin at your rate"),
			`<span style="color:var(--text-on-${colour}, inherit)">${margin}%</span>`,
			__("current rate {0}", [money(cur)])
		);
	}

	const stock = (d.stock || []).length
		? `<table class="table table-bordered table-sm" style="margin-top:8px">
		     <thead><tr><th>${__("Warehouse")}</th><th class="text-right">${__("Available")}</th>
		     <th class="text-right">${__("Reserved")}</th></tr></thead><tbody>
		     ${d.stock
					.map(
						(s) => `<tr><td>${frappe.utils.escape_html(s.warehouse)}</td>
					          <td class="text-right">${flt(s.actual_qty)}</td>
					          <td class="text-right">${flt(s.reserved_qty) || ""}</td></tr>`
					)
					.join("")}
		   </tbody></table>`
		: `<p class="text-muted">${__("No stock in your branch warehouses.")}</p>`;

	const dialog = new frappe.ui.Dialog({
		title: __("Price Assist — {0}", [d.item_name || d.item_code]),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "body" }],
		primary_action_label: d.price_list_rate ? __("Use price list rate") : null,
		primary_action: d.price_list_rate
			? () => {
					frappe.model.set_value(row.doctype, row.name, "rate", d.price_list_rate);
					dialog.hide();
			  }
			: null,
	});

	dialog.fields_dict.body.$wrapper.html(`
		<table class="table table-borderless table-sm">${rows}</table>
		<div style="font-weight:600;margin-top:6px">${__("Stock")}</div>
		${stock}
		<div style="margin-top:10px">
			<button class="btn btn-xs btn-default yht-history">${__("Show price history")}</button>
			${mine ? `<button class="btn btn-xs btn-default yht-use-last" style="margin-left:6px">${__("Use last rate to this customer")}</button>` : ""}
		</div>
		<div class="yht-history-out" style="margin-top:8px"></div>
	`);

	dialog.$wrapper.find(".yht-use-last").on("click", () => {
		frappe.model.set_value(row.doctype, row.name, "rate", mine.rate);
		dialog.hide();
	});

	dialog.$wrapper.find(".yht-history").on("click", function () {
		const $out = dialog.$wrapper.find(".yht-history-out");
		$out.html(`<span class="text-muted">${__("Loading…")}</span>`);
		yht_custom.price.fetch_history(frm, d.item_code, (rows) => {
			$out.html(yht_custom.price.history_table(rows));
		});
	});

	dialog.show();
};

// Quiet inline hint on the rate field — no dialog, no extra click.
yht_custom.price.hint = function (frm, row) {
	if (!row || !row.item_code || !flt(row.rate)) return;
	frappe.call({
		method: "yht_custom.api.price_assist.get_price_assist",
		args: {
			item_code: row.item_code,
			customer: frm.doc.customer || null,
			company: frm.doc.company,
			price_list: frm.doc.selling_price_list,
			qty: row.qty || 1,
		},
		callback(r) {
			const d = r.message;
			if (!d) return;
			const mine = d.last_to_this_customer;
			if (!mine) return;
			const diff = flt(row.rate) - flt(mine.rate);
			if (Math.abs(diff) < 0.01) return;
			const dir = diff < 0 ? __("below") : __("above");
			frappe.show_alert(
				{
					message: __("{0} is {1} {2} the last rate to this customer ({3})", [
						frappe.utils.escape_html(row.item_code),
						format_currency(Math.abs(diff), d.currency),
						dir,
						format_currency(mine.rate, d.currency),
					]),
					indicator: diff < 0 ? "orange" : "blue",
				},
				7
			);
		},
	});
};

// ---------------------------------------------------------------- price history
//
// Reachable two ways on purpose: the `Show Price History` grid button opens it
// directly for the current row, and the Price Assist dialog can expand it inline
// once the operator is already looking at the rates. Both go through the same
// fetch and the same table so the two views can never drift.

yht_custom.price.fetch_history = function (frm, item_code, done) {
	frappe.call({
		method: "yht_custom.api.price_assist.get_price_history",
		args: { item_code: item_code, company: frm.doc.company, limit: 30 },
		callback(r) {
			done(r.message || []);
		},
	});
};

yht_custom.price.history_table = function (rows) {
	if (!rows.length) return `<span class="text-muted">${__("No history.")}</span>`;
	return `<table class="table table-bordered table-sm">
		<thead><tr>
			<th>${__("Date")}</th><th>${__("Customer")}</th>
			<th class="text-right">${__("Qty")}</th><th class="text-right">${__("Rate")}</th>
			<th>${__("Invoice")}</th>
		</tr></thead><tbody>
		${rows
			.map(
				(x) => `<tr>
					<td>${frappe.datetime.str_to_user(x.posting_date)}</td>
					<td>${frappe.utils.escape_html(x.customer_name || x.customer || "")}</td>
					<td class="text-right">${flt(x.qty)}</td>
					<td class="text-right">${format_currency(x.rate, x.currency)}</td>
					<td><a href="/app/sales-invoice/${encodeURIComponent(x.invoice)}">${frappe.utils.escape_html(x.invoice)}</a></td>
				</tr>`
			)
			.join("")}
	</tbody></table>`;
};

yht_custom.price.open_history = function (frm) {
	const row = yht_custom.price.current_row(frm);
	if (!row) {
		frappe.msgprint(__("Add an item row first."));
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Price History — {0}", [row.item_name || row.item_code]),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "body" }],
	});
	dialog.fields_dict.body.$wrapper.html(`<span class="text-muted">${__("Loading…")}</span>`);
	dialog.show();

	yht_custom.price.fetch_history(frm, row.item_code, (rows) => {
		dialog.fields_dict.body.$wrapper.html(yht_custom.price.history_table(rows));
	});
};
