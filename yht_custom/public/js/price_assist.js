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

	// Both ask which line when there is more than one, so an earlier row is always reachable.
	grid.add_custom_button(__("Price Assist"), () =>
		yht_custom.price.pick_row(frm, (row) => yht_custom.price.open(frm, row)));
	grid.add_custom_button(__("Show Price History"), () =>
		yht_custom.price.pick_row(frm, (row) => yht_custom.price.open_history(frm, row)));
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

yht_custom.price.open = function (frm, explicit) {
	const row = explicit || yht_custom.price.current_row(frm);
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
		yht_custom.price.fetch_history(frm, d.item_code, ({ rows, summary }) => {
			$out.html(
				yht_custom.price.history_summary(summary, d.currency) +
					yht_custom.price.history_table(rows)
			);
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
		args: {
			item_code: item_code,
			customer: frm.doc.customer || null,
			company: frm.doc.company,
			limit: 30,
		},
		callback(r) {
			// The API returns { rows, summary }. It used to return a bare array; anything still
			// expecting that shape would silently render an empty table, so normalise here.
			const m = r.message || {};
			done(Array.isArray(m) ? { rows: m, summary: {} } : { rows: m.rows || [], summary: m.summary || {} });
		},
	});
};

/**
 * What we paid and what is on the shelf, above the sales table.
 *
 * An operator asking "what has this sold for" nearly always also wants "what did we pay" and
 * "have we got any". Making them close this and open Price Assist was two clicks for one
 * question.
 */
yht_custom.price.history_summary = function (summary, currency) {
	if (!summary || !Object.keys(summary).length) return "";
	const money = (v) =>
		v === null || v === undefined ? `<span class="text-muted">—</span>` : format_currency(v, currency);
	const qty = (v) => (v === null || v === undefined ? "—" : flt(v));

	const cells = [
		[__("Last purchase"), money(summary.last_purchase_rate),
			summary.last_purchase_date ? frappe.datetime.str_to_user(summary.last_purchase_date) : ""],
		[__("Buying list"), money(summary.buying_price_list_rate),
			summary.buying_price_list ? frappe.utils.escape_html(summary.buying_price_list) : ""],
		[__("Valuation"), money(summary.valuation_rate), ""],
		[__("Available"), `<b>${qty(summary.available_qty)}</b> ${frappe.utils.escape_html(summary.stock_uom || "")}`,
			flt(summary.reserved_qty) ? __("{0} reserved", [flt(summary.reserved_qty)]) : ""],
	];

	const warehouses = (summary.stock || []).length
		? `<table class="table table-bordered table-sm" style="margin-top:10px">
		     <thead><tr><th>${__("Warehouse")}</th><th class="text-right">${__("Available")}</th>
		     <th class="text-right">${__("Reserved")}</th></tr></thead><tbody>
		     ${summary.stock.map((row) => `<tr>
		         <td>${frappe.utils.escape_html(row.warehouse)}</td>
		         <td class="text-right">${flt(row.actual_qty)}</td>
		         <td class="text-right">${flt(row.reserved_qty) || ""}</td></tr>`).join("")}
		   </tbody></table>`
		: `<p class="text-muted" style="margin-top:8px">${__("No stock in your branch warehouses.")}</p>`;

	return `<div class="yht-hist-summary">
		${cells.map(([label, value, note]) => `<div class="yht-hist-cell">
			<div class="yht-hist-label">${label}</div>
			<div class="yht-hist-value">${value}</div>
			${note ? `<div class="yht-hist-note">${note}</div>` : ""}
		</div>`).join("")}
	</div>${warehouses}
	<div style="font-weight:600;margin-top:14px">${__("Recent sales")}</div>`;
};

yht_custom.price.history_table = function (rows) {
	if (!rows.length) return `<span class="text-muted">${__("No sales history for this item.")}</span>`;
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

yht_custom.price.open_history = function (frm, row) {
	const target = row || yht_custom.price.current_row(frm);
	if (!target) {
		frappe.msgprint(__("Add an item row first."));
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Price History — {0}", [target.item_name || target.item_code]),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "body" }],
	});
	dialog.fields_dict.body.$wrapper.html(`<span class="text-muted">${__("Loading…")}</span>`);
	dialog.show();

	yht_custom.price.fetch_history(frm, target.item_code, ({ rows, summary }) => {
		dialog.fields_dict.body.$wrapper.html(
			yht_custom.price.history_summary(summary, frm.doc.currency) +
				yht_custom.price.history_table(rows)
		);
	});
};

// ─────────────────────────────────────────────────────────────────────────────
// Reaching an EARLIER row
//
// The grid-footer buttons act on "the current row", which is the open grid form or, failing
// that, the last row with an item. Once a few lines are on the invoice that is no help: the
// operator wants row 2 again, and closing and reopening rows to get there is worse than not
// having the feature.
//
// Two answers, both wired below:
//   1. DOUBLE-CLICK the rate cell of any row — opens Price Assist for THAT row.
//   2. The footer buttons, when there is more than one row, ask which row first.
// ─────────────────────────────────────────────────────────────────────────────

/** Resolve the child row a grid DOM node belongs to. */
yht_custom.price.row_from_node = function (frm, node) {
	const $row = $(node).closest(".grid-row");
	const name = $row.attr("data-name");
	if (name && locals[frm.doc.doctype + " Item"]) {
		const byName = (frm.doc.items || []).find((r) => r.name === name);
		if (byName) return byName;
	}
	// Fall back to the visible index — the grid renders rows in doc order.
	const idx = cint($row.find(".row-index, .grid-static-col").first().text());
	return (frm.doc.items || []).find((r) => r.idx === idx) || null;
};

/** Ask which row, when the answer is not obvious. */
yht_custom.price.pick_row = function (frm, then) {
	const rows = (frm.doc.items || []).filter((r) => r.item_code);
	if (!rows.length) {
		frappe.msgprint(__("Add an item row first."));
		return;
	}
	if (rows.length === 1) {
		then(rows[0]);
		return;
	}

	const open = frappe.ui.form.get_open_grid_form();
	if (open && open.doc && open.doc.item_code) {
		then(open.doc);
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Which line?"),
		fields: [
			{
				fieldtype: "Select",
				fieldname: "row",
				label: __("Item"),
				reqd: 1,
				options: rows.map((r) => `${r.idx}: ${r.item_code}`).join("\n"),
				default: `${rows[rows.length - 1].idx}: ${rows[rows.length - 1].item_code}`,
			},
			{
				fieldtype: "HTML",
				options: `<p class="text-muted" style="margin-top:6px">${__(
					"Tip: double-click the Rate of any line to jump straight there."
				)}</p>`,
			},
		],
		primary_action_label: __("Show"),
		primary_action(values) {
			const idx = cint((values.row || "").split(":")[0]);
			const picked = rows.find((r) => r.idx === idx);
			dialog.hide();
			if (picked) then(picked);
		},
	});
	dialog.show();
};

// Double-click a Rate cell to open Price Assist for that line.
//
// Bound once, delegated from the document, because the grid tears down and rebuilds its rows
// constantly — a handler attached to a row does not survive the next render. Scoped to the
// selling doctypes Price Assist actually answers for: its rows are "last rate to THIS
// customer" and a recent selling band, which mean nothing on a purchase document.
$(document).on("dblclick", '.grid-row [data-fieldname="rate"]', function (e) {
	const frm = window.cur_frm;
	if (!frm || !SELLING.includes(frm.doc.doctype) || frm.doc.docstatus !== 0) return;
	const row = yht_custom.price.row_from_node(frm, this);
	if (!row || !row.item_code) return;
	e.preventDefault();
	e.stopPropagation();
	yht_custom.price.open(frm, row);
});
