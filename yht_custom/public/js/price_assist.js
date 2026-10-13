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

	// Row 13 (2026-10-11): ONE button, "Show Sales History", opening the unified popup. The
	// client's UAT round (2026-10-13) found "Price Assist" beside it doing the same thing, so
	// with the switch on it is not added at all. Behind the switch — this file is served to the
	// live site as soon as it is pulled, and with the switch off both old buttons stay.
	// Both ask which line when there is more than one, so an earlier row is always reachable.
	if (yht_custom.price.sales_history_on()) {
		grid.add_custom_button(__("Show Sales History"), () =>
			yht_custom.price.pick_row(frm, (row) => yht_custom.price.open_sales_history(frm, row)));
		return;
	}
	grid.add_custom_button(__("Price Assist"), () =>
		yht_custom.price.pick_row(frm, (row) => yht_custom.price.open(frm, row)));
	grid.add_custom_button(__("Show Price History"), () =>
		yht_custom.price.pick_row(frm, (row) => yht_custom.price.open_history(frm, row)));
}

yht_custom.price.sales_history_on = function () {
	return ((frappe.boot && frappe.boot.yht_features) || []).indexOf("oct11_r13_sales_history") !== -1;
};

// Opening it from a rate field is the natural gesture, so wire the item table too.
frappe.ui.form.on("Sales Invoice Item", {
	rate(frm, cdt, cdn) {
		yht_custom.price.hint(frm, locals[cdt][cdn]);
	},
});

// Row 13 — the Valuation Rate column is filled when the ITEM changes on a draft, never on
// `refresh` (that would dirty every draft that is merely opened). A row that already holds a
// value keeps it until its item changes.
const fill_valuation_on_item = {
	item_code(frm, cdt, cdn) {
		yht_custom.price.fill_valuation(frm, cdt, cdn);
	},
};
frappe.ui.form.on("Quotation Item", fill_valuation_on_item);
frappe.ui.form.on("Sales Order Item", fill_valuation_on_item);
frappe.ui.form.on("Sales Invoice Item", fill_valuation_on_item);
frappe.ui.form.on("Delivery Note Item", fill_valuation_on_item);

yht_custom.price.current_row = function (frm) {
	const open = frappe.ui.form.get_open_grid_form();
	if (open && open.doc && open.doc.item_code) return open.doc;
	const rows = (frm.doc.items || []).filter((r) => r.item_code);
	return rows.length ? rows[rows.length - 1] : null;
};

yht_custom.price.open = function (frm, explicit) {
	// Row 13 — one implementation: the Price Assist button opens the same popup.
	if (yht_custom.price.sales_history_on()) return yht_custom.price.open_sales_history(frm, explicit);
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

/**
 * The rate-comparison rows (price list, last sale to this customer / anyone, recent range,
 * valuation, margin). Shared by the Price Assist dialog and, at the bottom of the unified
 * popup, by `render_assist_block`.
 */
yht_custom.price.assist_rows = function (d, row) {
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
	return rows;
};

yht_custom.price.show = function (frm, row, d) {
	const mine = d.last_to_this_customer;
	const rows = yht_custom.price.assist_rows(d, row);

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
			<button class="btn btn-xs btn-default yht-purchases" style="margin-left:6px">${__("Show purchase history")}</button>
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

	// Both history buttons render into the SAME output div, so one replaces the other
	// rather than stacking two long tables the operator has to scroll past each other.
	dialog.$wrapper.find(".yht-purchases").on("click", function () {
		const $out = dialog.$wrapper.find(".yht-history-out");
		$out.html(`<span class="text-muted">${__("Loading…")}</span>`);
		yht_custom.price.fetch_purchase_history(frm, d.item_code, ({ rows }) => {
			$out.html(
				`<div style="font-weight:600;margin-top:6px">${__("Recent purchases")}</div>` +
					yht_custom.price.purchase_table(rows)
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

// ------------------------------------------------------------- purchase history
//
// The buying counterpart of fetch_history. Separate endpoint rather than an extra key on
// the price-history payload: an operator opens one or the other, and loading thirty
// purchase rows on every "what has this sold for" would be work nobody asked for.

yht_custom.price.fetch_purchase_history = function (frm, item_code, done) {
	frappe.call({
		method: "yht_custom.api.price_assist.get_purchase_history",
		args: {
			item_code: item_code,
			// NOTE: no supplier filter. Price Assist runs on the SELLING doctypes, so
			// `frm.doc` has a customer and no supplier — the question here is "what have we
			// paid for this", from anyone.
			company: frm.doc.company,
			limit: 30,
		},
		callback(r) {
			const m = r.message || {};
			done({ rows: m.rows || [] });
		},
	});
};

yht_custom.price.purchase_table = function (rows) {
	if (!rows.length) return `<span class="text-muted">${__("No purchase history for this item.")}</span>`;
	return `<table class="table table-bordered table-sm">
		<thead><tr>
			<th>${__("Date")}</th><th>${__("Supplier")}</th>
			<th class="text-right">${__("Qty")}</th><th class="text-right">${__("Rate")}</th>
			<th>${__("Invoice")}</th><th>${__("Supplier Bill")}</th>
		</tr></thead><tbody>
		${rows
			.map(
				(x) => `<tr>
					<td>${frappe.datetime.str_to_user(x.posting_date)}</td>
					<td>${frappe.utils.escape_html(x.supplier_name || x.supplier || "")}</td>
					<td class="text-right">${flt(x.qty)} ${frappe.utils.escape_html(x.uom || "")}</td>
					<td class="text-right">${format_currency(x.rate, x.currency)}</td>
					<td><a href="/app/purchase-invoice/${encodeURIComponent(x.invoice)}">${frappe.utils.escape_html(x.invoice)}</a></td>
					<td>${frappe.utils.escape_html(x.bill_no || "")}</td>
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
	// The grid row carries both `data-name` (the child docname) and `data-idx` — verified in the
	// live DOM — so neither needs scraping out of the rendered text.
	const $row = $(node).closest(".grid-row");
	const name = $row.attr("data-name");
	const rows = frm.doc.items || [];
	return (
		rows.find((r) => r.name === name) ||
		rows.find((r) => r.idx === cint($row.attr("data-idx"))) ||
		null
	);
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
				// 🔴 THE TIP MUST NOT ADVERTISE A GESTURE THAT IS GONE. CR-019 removed
				// the double-click shortcut, and this line went on telling operators to
				// use it — found by re-reading the acceptance criterion ("confirm the
				// remaining button covers every case"), not by anything failing.
				fieldtype: "HTML",
				options: yht_custom.price.rate_shortcut_disabled()
					? `<p class="text-muted" style="margin-top:6px">${__(
							"Tip: open a line with the pencil first and this dialog is skipped."
					  )}</p>`
					: `<p class="text-muted" style="margin-top:6px">${__(
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

// Two quick clicks on a Rate cell open Price Assist for that line.
//
// 🔴 NOT a native `dblclick` handler. Frappe's own click handler swaps the static cell for an
// editable control, so the first and second clicks land on DIFFERENT DOM nodes and the browser
// never emits a dblclick at all — the binding looked correct and simply never fired. A real
// user hits exactly the same thing, so this is not a test artefact.
//
// Instead: watch clicks and pair them ourselves, keyed on the ROW rather than the node, which
// is immune to the cell being replaced in between. Delegated from the document because the grid
// tears down and rebuilds its rows constantly.
//
// Scoped to the selling doctypes Price Assist actually answers for — its rows are "last rate to
// THIS customer" and a recent selling band, which mean nothing on a purchase document.

const DOUBLE_CLICK_MS = 600;
let lastRateClick = { key: null, at: 0 };

// 🔴 CR-019 — THE CLIENT ASKED FOR THIS SHORTCUT TO GO, AND THEY ARE RIGHT.
//
// Reported as "when I click on the Rate column, Price Assist loads". It is not a
// single click: the handler below opens the dialog on a DOUBLE click. But a double
// click on a number is how anybody selects it to retype it — so an operator
// reaching for the Rate cell to change 190.00 gets a modal instead of a selection,
// and has to dismiss it before they can type. The CR's own words were "keep only
// the button".
//
// The button stays. `Price Assist` and `Show Price History` sit in the grid footer
// (see BUTTON PLACEMENT at the top of this file) and are unaffected, as is the
// quiet inline hint on `rate`, which is a toast and blocks nothing.
//
// Behind a switch because this file is served to the client's live site the moment
// it is pulled — see `yht_custom/features.py`. Checked BEFORE the `closest()` call
// so that with the switch on this listener does strictly less work per click than
// it does today.
yht_custom.price.rate_shortcut_disabled = function () {
	return (
		((frappe.boot && frappe.boot.yht_features) || []).indexOf("cr_019_no_rate_doubleclick") !== -1
	);
};

// 🔴 CAPTURE PHASE, and a native listener — not `$(document).on("click", …)`.
//
// The jQuery delegated handler was correctly bound (verified live: the selector was registered
// on document and matched six nodes) and still never ran, because frappe's own grid click
// handler calls stopPropagation before the event bubbles up to document. A bubble-phase
// listener on document can never see it.
//
// `addEventListener(..., true)` runs in the capture phase, on the way DOWN, so it fires before
// anything downstream can stop it. Nothing is prevented or stopped here — frappe's editor still
// opens exactly as it would; we only observe.
document.addEventListener(
	"click",
	function (event) {
		if (yht_custom.price.rate_shortcut_disabled()) return;

		const cell = event.target instanceof Element
			? event.target.closest('.grid-row [data-fieldname="rate"]')
			: null;
		if (!cell) return;

		const frm = window.cur_frm;
		if (!frm || !SELLING.includes(frm.doc.doctype) || cint(frm.doc.docstatus) !== 0) return;

		const gridRow = cell.closest(".grid-row");
		if (!gridRow) return;
		const key = `${frm.doc.name}:${gridRow.getAttribute("data-name") || gridRow.getAttribute("data-idx")}`;
		const now = Date.now();

		if (lastRateClick.key === key && now - lastRateClick.at < DOUBLE_CLICK_MS) {
			lastRateClick = { key: null, at: 0 };
			const row = yht_custom.price.row_from_node(frm, cell);
			if (row && row.item_code) yht_custom.price.open(frm, row);
			return;
		}
		lastRateClick = { key, at: now };
	},
	true
);

// ------------------------------------------------------------ row 13 — sales history
//
// ONE popup for the grid button, the Price Assist button and a click on the Valuation cell:
// (1) sales, (2) purchases, (3) stock, (4) the price comparison at the BOTTOM — no comparison
// above the fold. One `frappe.call`, branch-scoped on the server.

yht_custom.price.fill_valuation = function (frm, cdt, cdn) {
	if (!yht_custom.price.sales_history_on()) return;
	if (cint(frm.doc.docstatus) !== 0) return;
	const row = locals[cdt] && locals[cdt][cdn];
	if (!row || !row.item_code) return;
	const item_code = row.item_code;

	frappe.call({
		method: "yht_custom.api.price_assist.get_valuation_rates",
		args: { item_codes: JSON.stringify([item_code]), company: frm.doc.company },
		callback(r) {
			const rates = r.message || {};
			// The user may have changed the item again while this was in flight.
			if (!(item_code in rates) || row.item_code !== item_code) return;
			frappe.model.set_value(cdt, cdn, "custom_valuation_rate", flt(rates[item_code]));
		},
	});
};

yht_custom.price.open_sales_history = function (frm, explicit) {
	const row = explicit || yht_custom.price.current_row(frm);
	if (!row) {
		frappe.msgprint(__("Add an item row first."));
		return;
	}

	frappe.call({
		method: "yht_custom.api.price_assist.get_history_popup",
		args: {
			item_code: row.item_code,
			customer: frm.doc.customer || null,
			company: frm.doc.company,
			price_list: frm.doc.selling_price_list,
			qty: row.qty || 1,
			limit: 6,
		},
		freeze: true,
		freeze_message: __("Loading history…"),
		callback(r) {
			if (r.message) yht_custom.price.show_sales_history(frm, row, r.message);
		},
	});
};

yht_custom.price.show_sales_history = function (frm, row, d) {
	const dialog = new frappe.ui.Dialog({
		title: __("Sales History — {0}", [(d.assist && d.assist.item_name) || row.item_name || row.item_code]),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "body" }],
	});
	const section = (title, html) =>
		`<div style="font-weight:600;margin-top:10px">${title}</div>${html}`;

	dialog.fields_dict.body.$wrapper.html(
		section(__("Recent sales"), yht_custom.price.history_table(d.sales || [])) +
			section(
				__("Recent purchases"),
				d.can_see_purchases === false
					? `<span class="text-muted">${__("Purchase history is not available for your role.")}</span>`
					: yht_custom.price.purchases_table(d.purchases || [])
			) +
			section(__("Stock"), yht_custom.price.stock_table(d.stock || [])) +
			`<div class="yht-assist-block"></div>`
	);
	yht_custom.price.render_assist_block(dialog, frm, row, d.assist || {});
	dialog.show();
};

/**
 * The price comparison, at the bottom of the popup. The "use" buttons only render on a draft:
 * they write the rate, and a submitted document must not offer to.
 */
yht_custom.price.render_assist_block = function (dialog, frm, row, d) {
	const mine = d.last_to_this_customer;
	const draft = frm.doc.docstatus === 0;
	const $block = dialog.$wrapper.find(".yht-assist-block");

	$block.html(`
		<div style="font-weight:600;margin-top:14px">${__("Price comparison")}</div>
		<table class="table table-borderless table-sm">${yht_custom.price.assist_rows(d, row)}</table>
		${
			draft
				? `<div>
				${d.price_list_rate ? `<button class="btn btn-xs btn-default yht-use-list">${__("Use price list rate")}</button>` : ""}
				${mine ? `<button class="btn btn-xs btn-default yht-use-last" style="margin-left:6px">${__("Use last rate to this customer")}</button>` : ""}
			</div>`
				: ""
		}
	`);

	$block.find(".yht-use-list").on("click", () => {
		frappe.model.set_value(row.doctype, row.name, "rate", d.price_list_rate);
		dialog.hide();
	});
	$block.find(".yht-use-last").on("click", () => {
		frappe.model.set_value(row.doctype, row.name, "rate", mine.rate);
		dialog.hide();
	});
};

yht_custom.price.purchases_table = function (rows) {
	if (!rows.length) return `<span class="text-muted">${__("No purchase history for this item.")}</span>`;
	return `<table class="table table-bordered table-sm">
		<thead><tr>
			<th>${__("Date")}</th><th>${__("Supplier")}</th>
			<th class="text-right">${__("Qty")}</th><th class="text-right">${__("Rate")}</th>
			<th>${__("Document")}</th>
		</tr></thead><tbody>
		${rows
			.map(
				(x) => `<tr>
					<td>${frappe.datetime.str_to_user(x.posting_date)}</td>
					<td>${frappe.utils.escape_html(x.supplier_name || x.supplier || "")}</td>
					<td class="text-right">${flt(x.qty)} ${frappe.utils.escape_html(x.uom || "")}</td>
					<td class="text-right">${format_currency(x.rate, x.currency)}</td>
					<td>${frappe.utils.escape_html(x.doc_type)}
						<a href="/app/${encodeURIComponent(frappe.router.slug(x.doc_type))}/${encodeURIComponent(x.doc)}">${frappe.utils.escape_html(x.doc)}</a></td>
				</tr>`
			)
			.join("")}
	</tbody></table>`;
};

yht_custom.price.stock_table = function (rows) {
	if (!rows.length) return `<span class="text-muted">${__("No stock in your branch warehouses.")}</span>`;
	return `<table class="table table-bordered table-sm">
		<thead><tr><th>${__("Warehouse")}</th><th class="text-right">${__("Available")}</th>
		<th class="text-right">${__("Reserved")}</th></tr></thead><tbody>
		${rows
			.map(
				(x) => `<tr><td>${frappe.utils.escape_html(x.warehouse)}</td>
					<td class="text-right">${flt(x.actual_qty)}</td>
					<td class="text-right">${flt(x.reserved_qty) || ""}</td></tr>`
			)
			.join("")}
	</tbody></table>`;
};

// A click on a Valuation cell opens the same popup for that row, on any docstatus (it only
// reads). Capture phase and a native listener for the same reason as the Rate listener above:
// frappe's own grid handler stops propagation before a bubble-phase listener could see it.
// Nothing is prevented or stopped here. The Rate listener is untouched — double-click on Rate
// stays off (CR-019).
document.addEventListener(
	"click",
	function (event) {
		if (!yht_custom.price.sales_history_on()) return;

		const cell = event.target instanceof Element
			? event.target.closest('.grid-row [data-fieldname="custom_valuation_rate"]')
			: null;
		if (!cell) return;

		const frm = window.cur_frm;
		if (!frm || !SELLING.includes(frm.doc.doctype)) return;

		const row = yht_custom.price.row_from_node(frm, cell);
		if (row && row.item_code) yht_custom.price.open_sales_history(frm, row);
	},
	true
);
