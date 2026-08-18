// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Branch-user landing page.
//
// TWO THINGS TO REMEMBER WHEN CHANGING THIS FILE:
//   1. Adding a tile is a TWO-file change — add the destination doctype to
//      ALLOWED_DOCTYPES in public/js/branch_user_restrict.js too, or a restricted
//      user clicking it is bounced straight back here.
//   2. No `bench build` is needed (page JS was never bundled), but browsers cache
//      the whole page doc in localStorage under `_page:yht-dashboard`. That cache
//      only clears when the build version changes, which is the mtime of
//      sites/assets/assets.json. After deploying, run:
//         touch sites/assets/assets.json
//      Otherwise the change is invisible to everyone already signed in — forever.
//      clear-cache, a worker restart and a hard refresh all fail to fix it.

frappe.pages["yht-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Branch Dashboard"),
		single_column: true,
	});

	page.main.addClass("yht-dashboard");
	page.body = $('<div class="yht-dash-body"></div>').appendTo(page.main);

	wrapper.yht_page = page;
	load(page);

	page.set_secondary_action(__("Refresh"), () => load(page), "refresh");
};

frappe.pages["yht-dashboard"].on_page_show = function (wrapper) {
	if (wrapper.yht_page) load(wrapper.yht_page);
};

function load(page) {
	page.body.html(`<div class="text-muted p-4">${__("Loading…")}</div>`);
	frappe.call({
		method: "yht_custom.api.dashboard.get_dashboard_data",
		callback(r) {
			if (!r.message) {
				page.body.html(`<div class="text-muted p-4">${__("No data available.")}</div>`);
				return;
			}
			render(page, r.message);
		},
		error() {
			page.body.html(
				`<div class="text-danger p-4">${__("Could not load the dashboard. Please contact your administrator.")}</div>`
			);
		},
	});
}

function render(page, d) {
	const money = (v) => format_currency(v || 0, frappe.boot.sysdefaults.currency);
	const who = d.branch
		? __("Branch: {0}", [frappe.utils.escape_html(d.branch)])
		: __("All branches");

	const stats = [
		{ label: __("Sales Today"), value: money(d.sales_today) },
		{ label: __("Sales This Month"), value: money(d.sales_mtd) },
		{ label: __("Invoices This Month"), value: d.invoices_mtd || 0 },
		{ label: __("Outstanding"), value: money(d.outstanding) },
	];

	// Tile set per the MoM document list. Material Request and inter-branch
	// transfer are deliberately absent for branch users.
	const actions = [
		{ icon: "file", label: __("Sales Invoice"), doctype: "Sales Invoice", mode: "new" },
		{ icon: "small-file", label: __("Quotation"), doctype: "Quotation", mode: "list" },
		{ icon: "list", label: __("Sales Order"), doctype: "Sales Order", mode: "list" },
		{ icon: "delivery", label: __("Delivery Note"), doctype: "Delivery Note", mode: "list" },
		{ icon: "users", label: __("Customer"), doctype: "Customer", mode: "list" },
		{ icon: "money-coins-alt", label: __("Payment Entry"), doctype: "Payment Entry", mode: "list" },
		{ icon: "stock", label: __("Purchase Receipt"), doctype: "Purchase Receipt", mode: "list" },
		{ icon: "file", label: __("Purchase Invoice"), doctype: "Purchase Invoice", mode: "list" },
		{ icon: "package", label: __("Item"), doctype: "Item", mode: "list" },
	];

	const reports = [
		{ label: __("Stock Balance"), report: "Stock Balance" },
		{ label: __("Stock Ledger"), report: "Stock Ledger" },
		{ label: __("Accounts Receivable Summary"), report: "Accounts Receivable Summary" },
		{ label: __("General Ledger"), report: "General Ledger" },
	];

	const drafts = d.draft_counts || {};
	const draft_chips = Object.keys(drafts)
		.filter((k) => drafts[k] > 0)
		.map(
			(k) =>
				`<a class="yht-chip" href="/app/${frappe.router.slug(k)}?docstatus=0">
					${frappe.utils.escape_html(__(k))} <b>${drafts[k]}</b>
				 </a>`
		)
		.join("");

	page.body.html(`
		<div class="yht-head">
			<div class="yht-who">${who}</div>
			${draft_chips ? `<div class="yht-chips">${__("Drafts")}: ${draft_chips}</div>` : ""}
		</div>

		<div class="yht-stats">
			${stats
				.map(
					(s) => `<div class="yht-stat">
						<div class="yht-stat-label">${s.label}</div>
						<div class="yht-stat-value">${s.value}</div>
					</div>`
				)
				.join("")}
		</div>

		<div class="yht-section-title">${__("Documents")}</div>
		<div class="yht-grid">
			${actions.map(action_card).join("")}
		</div>

		<div class="yht-section-title">${__("Reports")}</div>
		<div class="yht-grid">
			${reports.map(report_card).join("")}
		</div>
	`);
}

function action_card(a) {
	const route =
		a.mode === "new"
			? `/app/${frappe.router.slug(a.doctype)}/new`
			: `/app/${frappe.router.slug(a.doctype)}`;
	return `<a class="yht-card" href="${route}">
		<span class="yht-card-icon">${frappe.utils.icon(a.icon, "md")}</span>
		<span class="yht-card-label">${frappe.utils.escape_html(a.label)}</span>
	</a>`;
}

function report_card(r) {
	const route = `/app/query-report/${encodeURIComponent(r.report)}`;
	return `<a class="yht-card" href="${route}">
		<span class="yht-card-icon">${frappe.utils.icon("small-file", "md")}</span>
		<span class="yht-card-label">${frappe.utils.escape_html(r.label)}</span>
	</a>`;
}
