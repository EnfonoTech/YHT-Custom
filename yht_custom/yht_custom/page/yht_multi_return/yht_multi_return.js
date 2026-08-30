// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Return goods spanning SEVERAL delivery notes in one pass.
//
// THREE THINGS TO REMEMBER WHEN CHANGING THIS FILE:
//
//   1. It still creates ONE return per source note. `Delivery Note.return_against`
//      is a single Link, and a hand-merged return SAVES AND SUBMITS with only the
//      first note linked — the second is silently never credited. Do not "improve"
//      this into one merged document.
//
//   2. No `bench build` is needed (page JS was never bundled), but browsers cache
//      the page doc in localStorage under `_page:yht-multi-return`. That cache only
//      clears when the build version changes, which is the mtime of
//      sites/assets/assets.json. After deploying, run:
//         touch sites/assets/assets.json
//      Otherwise the change is invisible to everyone already signed in — forever.
//
//   3. `yht-multi-return` must stay in ALLOWED_ROUTES in branch_user_restrict.js.
//      Absent from that list, a lone slug is treated as a doctype the role cannot
//      open and the branch user is bounced straight back to the dashboard.

frappe.pages["yht-multi-return"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Return From Several Delivery Notes"),
		single_column: true,
	});

	const state = { customer: null, notes: [], selected: {} };
	page.main.addClass("yht-multi-return");
	inject_styles();

	const customer_field = page.add_field({
		fieldname: "customer",
		label: __("Customer"),
		fieldtype: "Link",
		options: "Customer",
		reqd: 1,
		change: () => load(customer_field.get_value()),
	});

	const body = $('<div class="yht-mr-body"></div>').appendTo(page.main);
	const footer = $('<div class="yht-mr-footer hide"></div>').appendTo(page.main);

	page.set_primary_action(__("Create Returns"), () => confirm_and_create(), "add");
	page.set_secondary_action(__("Refresh"), () => load(state.customer, true), "refresh");
	page.btn_primary.prop("disabled", true);

	function load(customer, force) {
		state.customer = customer;
		state.selected = {};
		footer.addClass("hide");
		page.btn_primary.prop("disabled", true);
		if (!customer) {
			body.html(empty(__("Pick a customer to see what can come back.")));
			return;
		}
		body.html('<div class="yht-mr-loading text-muted">' + __("Loading…") + "</div>");
		frappe.call({
			method: "yht_custom.multi_return.returnable_delivery_notes",
			args: { customer },
			callback: (r) => {
				state.notes = r.message || [];
				render();
			},
		});
	}

	function render() {
		if (!state.notes.length) {
			body.html(
				empty(
					__("Nothing to return for {0}.", [frappe.utils.escape_html(state.customer)]) +
						"<br>" +
						__("Every delivery note is either unsubmitted or already fully returned.")
				)
			);
			return;
		}
		body.empty();
		$(
			'<div class="yht-mr-hint text-muted">' +
				__("One return is created per delivery note — {0} of them if you tick all.", [
					state.notes.length,
				]) +
				"</div>"
		).appendTo(body);

		state.notes.forEach((note) => body.append(note_card(note)));
		footer.html(footer_html()).removeClass("hide");
		bind_footer();
		recount();
	}

	function note_card(note) {
		const card = $('<div class="yht-mr-card"></div>').attr("data-note", note.name);
		const head = $(`
			<div class="yht-mr-head">
				<label class="yht-mr-check">
					<input type="checkbox" class="yht-mr-all">
					<span class="yht-mr-name">${frappe.utils.escape_html(note.name)}</span>
				</label>
				<span class="yht-mr-meta">
					${frappe.datetime.str_to_user(note.posting_date)} ·
					${frappe.format(note.grand_total, { fieldtype: "Currency", options: "currency" })} ·
					${frappe.utils.escape_html(note.status)}
				</span>
				<a class="yht-mr-open" href="/app/delivery-note/${encodeURIComponent(note.name)}"
				   target="_blank">${__("Open")}</a>
			</div>`).appendTo(card);

		const table = $(`
			<table class="table yht-mr-table">
				<thead><tr>
					<th style="width:34px"></th>
					<th>${__("Item")}</th>
					<th class="text-right">${__("Delivered")}</th>
					<th class="text-right">${__("Already Returned")}</th>
					<th class="text-right">${__("Can Return")}</th>
					<th class="text-right" style="width:130px">${__("Returning")}</th>
				</tr></thead>
				<tbody></tbody>
			</table>`).appendTo(card);

		note.items.forEach((item) => {
			$(`
				<tr data-row="${item.row_name}">
					<td><input type="checkbox" class="yht-mr-row"></td>
					<td>
						<div class="yht-mr-item">${frappe.utils.escape_html(item.item_code)}</div>
						<div class="text-muted small">${frappe.utils.escape_html(item.item_name || "")}</div>
					</td>
					<td class="text-right">${format_qty(item.delivered)} ${frappe.utils.escape_html(item.uom || "")}</td>
					<td class="text-right ${item.returned ? "" : "text-muted"}">${format_qty(item.returned)}</td>
					<td class="text-right yht-mr-max"><b>${format_qty(item.returnable)}</b></td>
					<td class="text-right">
						<input type="number" class="form-control input-sm yht-mr-qty text-right"
						       min="0" step="any" max="${item.returnable}"
						       value="${item.returnable}" disabled>
					</td>
				</tr>`).appendTo(table.find("tbody"));
		});

		head.find(".yht-mr-all").on("change", function () {
			const on = $(this).prop("checked");
			card.find(".yht-mr-row").prop("checked", on).trigger("change");
		});
		card.find(".yht-mr-row").on("change", function () {
			const tr = $(this).closest("tr");
			tr.toggleClass("is-on", $(this).prop("checked"));
			tr.find(".yht-mr-qty").prop("disabled", !$(this).prop("checked"));
			sync_note_checkbox(card);
			recount();
		});
		card.find(".yht-mr-qty").on("input", function () {
			// The max is the row remainder ERPNext will itself enforce at submit.
			// Clamping here turns a submit-time StockOverReturnError into a no-op.
			const max = flt($(this).attr("max"));
			if (flt($(this).val()) > max) $(this).val(max);
			recount();
		});
		return card;
	}

	function sync_note_checkbox(card) {
		const rows = card.find(".yht-mr-row");
		const on = card.find(".yht-mr-row:checked");
		card.find(".yht-mr-all").prop("checked", on.length === rows.length && rows.length > 0);
		card.find(".yht-mr-all").prop("indeterminate", on.length > 0 && on.length < rows.length);
	}

	function collect() {
		const out = [];
		body.find(".yht-mr-card").each(function () {
			const card = $(this);
			const rows = [];
			card.find(".yht-mr-row:checked").each(function () {
				const tr = $(this).closest("tr");
				const qty = flt(tr.find(".yht-mr-qty").val());
				if (qty > 0) rows.push({ row_name: tr.data("row"), qty });
			});
			if (rows.length) out.push({ delivery_note: card.data("note"), rows });
		});
		return out;
	}

	function recount() {
		const picked = collect();
		const lines = picked.reduce((n, p) => n + p.rows.length, 0);
		footer.find(".yht-mr-count").html(
			picked.length
				? __("{0} delivery note(s), {1} line(s) — {0} return(s) will be created.", [
						picked.length,
						lines,
				  ])
				: __("Nothing selected yet.")
		);
		page.btn_primary.prop("disabled", !picked.length);
	}

	function footer_html() {
		return `
			<div class="yht-mr-footer-inner">
				<div class="yht-mr-count text-muted"></div>
				<div class="yht-mr-opts">
					<label><input type="checkbox" class="yht-mr-submit" checked> ${__(
						"Submit the returns"
					)}</label>
					<label><input type="checkbox" class="yht-mr-credit" checked> ${__(
						"Also raise credit notes"
					)}</label>
				</div>
			</div>`;
	}

	function bind_footer() {
		footer.find(".yht-mr-submit").on("change", function () {
			// A credit note can only be mapped from a SUBMITTED return, so the server
			// refuses the combination. Reflect that here instead of surfacing a throw.
			const on = $(this).prop("checked");
			footer.find(".yht-mr-credit").prop("disabled", !on);
			if (!on) footer.find(".yht-mr-credit").prop("checked", false);
		});
	}

	function confirm_and_create() {
		const picked = collect();
		if (!picked.length) return;
		const submit = footer.find(".yht-mr-submit").prop("checked") ? 1 : 0;
		const credit = footer.find(".yht-mr-credit").prop("checked") ? 1 : 0;

		const what = picked
			.map(
				(p) =>
					"<li><b>" +
					frappe.utils.escape_html(p.delivery_note) +
					"</b> — " +
					__("{0} line(s)", [p.rows.length]) +
					"</li>"
			)
			.join("");

		frappe.confirm(
			__("This creates {0} delivery return(s):", [picked.length]) +
				"<ul>" +
				what +
				"</ul>" +
				(submit
					? "<p>" +
					  __("They will be <b>submitted</b>, which moves stock back in{0}.", [
							credit ? __(" and raises a credit note against each original invoice") : "",
					  ]) +
					  "</p>"
					: "<p>" + __("They will be left as <b>drafts</b> for you to check.") + "</p>"),
			() => run(picked, submit, credit)
		);
	}

	function run(picked, submit, credit) {
		frappe.dom.freeze(__("Creating returns…"));
		frappe.call({
			method: "yht_custom.multi_return.create_returns",
			args: {
				customer: state.customer,
				selections: JSON.stringify(picked),
				submit,
				raise_credit_notes: credit,
			},
			always: () => frappe.dom.unfreeze(),
			callback: (r) => show_result(r.message || {}),
		});
	}

	function show_result(result) {
		const made = result.created || [];
		const bad = result.failed || [];
		let html = "";
		if (made.length) {
			html +=
				"<p><b>" +
				__("Created {0} return(s):", [made.length]) +
				"</b></p><ul>" +
				made
					.map(
						(m) =>
							"<li>" +
							link("Delivery Note", m["return"]) +
							" ← " +
							frappe.utils.escape_html(m.delivery_note) +
							(m.credit_note
								? " · " +
								  link("Sales Invoice", m.credit_note) +
								  (m.settles
										? " " +
										  __("settles {0}", [
												link("Sales Invoice", m.settles),
										  ])
										: "")
								: "") +
							"</li>"
					)
					.join("") +
				"</ul>";
		}
		if (bad.length) {
			html +=
				'<p class="text-danger"><b>' +
				__("{0} could not be created:", [bad.length]) +
				"</b></p><ul>" +
				bad
					.map(
						(b) =>
							"<li>" +
							frappe.utils.escape_html(b.delivery_note) +
							" — <span class='text-danger'>" +
							frappe.utils.escape_html(b.error) +
							"</span></li>"
					)
					.join("") +
				"</ul>";
		}
		frappe.msgprint({
			title: bad.length ? __("Finished with errors") : __("Done"),
			indicator: bad.length ? "orange" : "green",
			message: html || __("Nothing was created."),
		});
		load(state.customer, true);
	}

	function link(doctype, name) {
		if (!name) return "";
		return (
			'<a href="/app/' +
			frappe.router.slug(doctype) +
			"/" +
			encodeURIComponent(name) +
			'" target="_blank">' +
			frappe.utils.escape_html(name) +
			"</a>"
		);
	}

	function empty(message) {
		return '<div class="yht-mr-empty text-muted">' + message + "</div>";
	}

	function format_qty(value) {
		return format_number(flt(value), null, 2).replace(/\.00$/, "");
	}

	function inject_styles() {
		if (document.getElementById("yht-mr-styles")) return;
		$(
			`<style id="yht-mr-styles">
			.yht-mr-body { margin-top: 12px; padding-bottom: 92px; }
			.yht-mr-hint { margin: 0 0 10px 2px; font-size: 12px; }
			.yht-mr-empty { padding: 42px 12px; text-align: center; }
			.yht-mr-card { border: 1px solid var(--border-color); border-radius: 8px;
				margin-bottom: 12px; background: var(--card-bg); overflow: hidden; }
			/* nowrap, NOT wrap: with wrap the meta is squeezed to ~74px and the date,
			   total and status stack into three lines, making the header taller than
			   the rows it labels. The meta takes the slack and ellipsises instead. */
			.yht-mr-head { display: flex; align-items: center; gap: 12px; flex-wrap: nowrap;
				padding: 10px 14px; background: var(--subtle-fg); border-bottom: 1px solid var(--border-color); }
			.yht-mr-check { display: flex; align-items: center; gap: 8px; margin: 0; cursor: pointer;
				flex: 0 0 auto; }
			.yht-mr-name { font-weight: 600; white-space: nowrap; }
			/* nowrap, or the date/total/status stack into three lines and the header
			   grows taller than the rows it labels. */
			.yht-mr-meta { color: var(--text-muted); font-size: 12px; white-space: nowrap;
				overflow: hidden; text-overflow: ellipsis; flex: 1 1 auto; min-width: 0; }
			.yht-mr-open { margin-left: auto; font-size: 12px; flex: 0 0 auto; }
			.yht-mr-table { margin: 0; }
			.yht-mr-table th { font-size: 11px; text-transform: uppercase; letter-spacing: .3px;
				color: var(--text-muted); font-weight: 600; border-top: 0; }
			.yht-mr-table td { vertical-align: middle; }
			.yht-mr-table tr.is-on { background: var(--highlight-color); }
			.yht-mr-item { font-weight: 500; }
			.yht-mr-qty { display: inline-block; width: 110px; }
			.yht-mr-footer { position: sticky; bottom: 0; background: var(--card-bg);
				border-top: 1px solid var(--border-color); padding: 12px 14px; margin-top: 8px; }
			.yht-mr-footer-inner { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
			.yht-mr-opts { margin-left: auto; display: flex; gap: 18px; }
			.yht-mr-opts label { margin: 0; font-weight: normal; display: flex; align-items: center; gap: 6px; }
			</style>`
		).appendTo(document.head);
	}
};
