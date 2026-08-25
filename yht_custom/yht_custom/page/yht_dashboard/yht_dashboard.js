// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Branch-user landing page.
//
// THREE THINGS TO REMEMBER WHEN CHANGING THIS FILE:
//
//   1. Adding a tile is a TWO-file change — add the destination doctype to
//      ALLOWED_DOCTYPES in public/js/branch_user_restrict.js too, or a restricted
//      user clicking it is bounced straight back here.
//
//   2. No `bench build` is needed (page JS was never bundled), but browsers cache
//      the whole page doc in localStorage under `_page:yht-dashboard`. That cache
//      only clears when the build version changes, which is the mtime of
//      sites/assets/assets.json. After deploying, run:
//         touch sites/assets/assets.json
//      Otherwise the change is invisible to everyone already signed in — forever.
//      clear-cache, a worker restart and a hard refresh all fail to fix it.
//
//   3. Icon names MUST exist in frappe's sprite
//      (apps/frappe/frappe/public/icons/timeless/icons.svg — 178 of them), because
//      frappe.utils.icon() fails SILENTLY on an unknown name and leaves an empty
//      slot. This page therefore carries its OWN inline SVG set below rather than
//      the sprite: the sprite has no usable glyph for several of these tiles, and
//      an inline path cannot fail silently.

frappe.pages["yht-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Branch Dashboard"),
		single_column: true,
	});

	page.main.addClass("yht-dashboard");
	page.body = $('<div class="yht-dash"></div>').appendTo(page.main);

	wrapper.yht_page = page;
	load(page, { showSpinner: true });

	page.set_secondary_action(__("Refresh"), () => load(page, { force: true, showSpinner: true }), "refresh");
};

frappe.pages["yht-dashboard"].on_page_show = function (wrapper) {
	// Render the LAST payload immediately, then revalidate quietly behind it.
	//
	// The first version blanked the page and refetched on every single page show, so every
	// trip back to the dashboard — which is the whole navigation model of this role — showed
	// "Loading dashboard…" again from scratch. The server side is not the problem: the payload
	// measures ~730ms. Throwing away an already-rendered screen is.
	//
	// So: paint from cache instantly if we have one, and only show the spinner when there is
	// genuinely nothing to show. The Refresh button always forces a visible reload.
	if (!wrapper.yht_page) return;
	load(wrapper.yht_page, { showSpinner: !CACHE.data });
};

//: Last payload, and when it was fetched. Lives for the session, on purpose — the numbers are
//: a branch's running totals, not something that must be to-the-second.
const CACHE = { data: null, at: 0 };
const STALE_MS = 60 * 1000;

function load(page, { force = false, showSpinner = false } = {}) {
	const fresh = CACHE.data && Date.now() - CACHE.at < STALE_MS;

	if (CACHE.data) render(page, CACHE.data);
	else if (showSpinner) {
		page.body.html(`
			<div class="yht-loading">
				<div class="yht-spinner"></div>
				<span>${__("Loading dashboard…")}</span>
			</div>`);
	}

	// Nothing to do if the cached copy is still warm and nobody asked for a reload.
	if (fresh && !force) return;

	frappe.call({
		method: "yht_custom.api.dashboard.get_dashboard_data",
		callback(r) {
			if (!r.message) {
				if (!CACHE.data) page.body.html(`<div class="yht-empty">${__("No data available.")}</div>`);
				return;
			}
			CACHE.data = r.message;
			CACHE.at = Date.now();
			render(page, r.message);
		},
		error() {
			// Keep whatever is on screen if we have something — a failed refresh should not
			// wipe a working dashboard.
			if (CACHE.data) return;
			page.body.html(
				`<div class="yht-error">${__(
					"Could not load the dashboard. Please contact your administrator."
				)}</div>`
			);
		},
	});
}

// ------------------------------------------------------------------ icon set
//
// Feather-style 24x24 stroke paths, drawn with currentColor so they follow the
// tile's own colour in both themes. Inline rather than sprite — see note 3 above.

const ICONS = {
	invoice:
		'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
	quote:
		'<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><line x1="8" y1="9" x2="16" y2="9"/><line x1="8" y1="13" x2="13" y2="13"/>',
	order:
		'<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/><polyline points="9 14 11 16 15 12"/>',
	truck:
		'<rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>',
	people:
		'<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
	card: '<rect x="1" y="4" width="22" height="16" rx="2"/><line x1="1" y1="10" x2="23" y2="10"/>',
	box: '<line x1="16.5" y1="9.4" x2="7.5" y2="4.21"/><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>',
	expense:
		'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><polyline points="9 15 12 12 15 15"/>',
	tag: '<path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/>',
	layers:
		'<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
	book: '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
	activity: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
	ledger:
		'<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
	statement:
		'<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
	trend:
		'<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>',
	wallet:
		'<path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4z"/>',
	clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
};

function icon(name) {
	return `<svg class="yht-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
		stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ""}</svg>`;
}

// ------------------------------------------------------------------- tile set
//
// Per the MoM document list. Material Request and inter-branch transfer are
// deliberately absent for branch users.

const ACTIONS = [
	{ icon: "invoice", label: "Sales Invoice", desc: "Create new invoice", doctype: "Sales Invoice", mode: "new" },
	{ icon: "quote", label: "Quotation", desc: "View quotations", doctype: "Quotation", mode: "list" },
	{ icon: "order", label: "Sales Order", desc: "View orders", doctype: "Sales Order", mode: "list" },
	{ icon: "truck", label: "Delivery Note", desc: "View delivery notes", doctype: "Delivery Note", mode: "list" },
	{ icon: "people", label: "Customer", desc: "Manage customers", doctype: "Customer", mode: "list" },
	{ icon: "people", label: "New Customer", desc: "Quick create", dialog: "Customer" },
	{ icon: "card", label: "Payment Entry", desc: "Record payments", doctype: "Payment Entry", mode: "list" },
	{ icon: "box", label: "Purchase Receipt", desc: "View receipts", doctype: "Purchase Receipt", mode: "list" },
	{ icon: "expense", label: "Purchase Invoice", desc: "View invoices", doctype: "Purchase Invoice", mode: "list" },
	{ icon: "tag", label: "Item", desc: "Browse items", doctype: "Item", mode: "list" },
];

const REPORTS = [
	{ icon: "trend", label: "Stock Sales", desc: "Sold by item or customer", report: "Stock Sales" },
	{ icon: "wallet", label: "Collection", desc: "Money received", report: "Collection" },
	{ icon: "clock", label: "Branch Receivables", desc: "Outstanding, aged", report: "Branch Receivables" },
	{ icon: "layers", label: "Stock Balance", desc: "Current stock levels", report: "Stock Balance" },
	// 🔴 THESE TWO TILES POINT AT THE KATC REPORTS, NOT ERPNEXT'S.
	// Client sheet items 7 and 8 ask for a stock ledger and a general ledger with
	// THEIR column list — qty in and qty out as two columns rather than one signed
	// number, and six columns on the GL instead of eighteen. Leaving the tiles on
	// ERPNext's reports would train every branch user on the report the client
	// asked to have replaced. ERPNext's originals stay reachable by search and on
	// the KATC Reports workspace for anyone who wants them.
	{ icon: "book", label: "Stock Ledger", desc: "Every movement, in and out", report: "KATC Stock Ledger" },
	{ icon: "activity", label: "Receivables Summary", desc: "Party-wise aging", report: "Accounts Receivable Summary" },
	{ icon: "ledger", label: "General Ledger", desc: "One account, running balance", report: "KATC General Ledger" },
	// Item 9 — one party's ledger, which is the question asked when a customer rings.
	{ icon: "statement", label: "Party Ledger", desc: "One customer or supplier", report: "KATC Party and Account Ledger" },
	// This tile said "Customer Statement" and opened General Ledger from the day the
	// dashboard was built — a different name, different filters, every party in the
	// company on it. It now opens the report it always claimed to.
	{ icon: "statement", label: "Customer Statement", desc: "One customer, aged", report: "Customer Statement" },
	{ icon: "tag", label: "Item Prices", desc: "Price list rates", report: "Item-wise Price List Rate" },
];

// ---------------------------------------------------------------------- render

function render(page, d) {
	const currency = d.currency || frappe.boot.sysdefaults.currency;
	const money = (v) => format_currency(v || 0, currency);
	// KPI figures are abbreviated and carry the currency in the LABEL, not beside
	// the number: at 32px a formatted SAR amount wraps, and a wrapped figure reads
	// as two numbers. The exact amounts live in Needs Attention and the lists.
	const short = (v) => short_number(v);

	const title = d.branch
		? `${frappe.utils.escape_html(d.branch)} <span class="yht-title-suffix">${__("Branch")}</span>`
		: __("All Branches");
	const subtitle = d.is_branch_user && !d.is_admin ? __("Sales Dashboard") : __("Overview Dashboard");

	const kpis = [
		{ tone: "today", label: __("Sales Today ({0})", [currency]), value: short(d.sales_today), icon: "ledger" },
		{ tone: "month", label: __("Sales This Month ({0})", [currency]), value: short(d.sales_mtd), icon: "activity" },
		{ tone: "count", label: __("Invoices This Month"), value: short_number(d.invoices_mtd), icon: "invoice" },
		{ tone: "warn", label: __("Overdue ({0})", [currency]), value: short(d.overdue), icon: "card" },
		{ tone: "danger", label: __("Outstanding ({0})", [currency]), value: short(d.outstanding), icon: "layers" },
	];

	const drafts = d.draft_counts || {};
	const chips = Object.keys(drafts)
		.filter((k) => drafts[k] > 0)
		.map(
			(k) => `<a class="yht-chip" href="/app/${frappe.router.slug(k)}?docstatus=0">
				${frappe.utils.escape_html(__(k))}<b>${drafts[k]}</b></a>`
		)
		.join("");

	page.body.html(`
		<div class="yht-header">
			<div>
				<h2 class="yht-title">${title}</h2>
				<span class="yht-subtitle">${subtitle}</span>
			</div>
			<div class="yht-header-right">
				<a class="yht-guide" href="/assets/yht_custom/guide/index.html" target="_blank"
				   rel="noopener">${__("User Guide")}</a>
				<span class="yht-date">${frappe.datetime.str_to_user(frappe.datetime.get_today())}</span>
			</div>
		</div>

		<div class="yht-kpi-row">${kpis.map(kpi_card).join("")}</div>

		${chips ? `<div class="yht-chips"><span class="yht-chips-label">${__("Drafts")}</span>${chips}</div>` : ""}

		<h3 class="yht-section">${__("Quick Actions")}</h3>
		<div class="yht-grid">${ACTIONS.map(action_card).join("")}</div>

		<h3 class="yht-section">${__("Reports")}</h3>
		<div class="yht-grid">${REPORTS.map(report_card).join("")}</div>

		${pending_section(d.pending || [], money)}
	`);

	// Stagger the cards in. 40ms apart is enough to read as one sweep rather than
	// a dozen unrelated pops.
	// Delegated so it survives every re-render of the tile grid.
	page.body.off("click.yht-dialog").on("click.yht-dialog", "[data-yht-dialog]", function (e) {
		e.preventDefault();
		const doctype = $(this).attr("data-yht-dialog");
		if (window.yht && yht.simple_party) yht.simple_party.open(doctype);
	});

	setTimeout(() => {
		page.body.find(".yht-kpi, .yht-card, .yht-pending-item").each(function (i) {
			const $el = $(this);
			setTimeout(() => $el.addClass("yht-in"), i * 40);
		});
	}, 50);
}

function kpi_card(k) {
	return `<div class="yht-kpi yht-kpi-${k.tone}">
		<div class="yht-kpi-top">
			<span class="yht-kpi-icon">${icon(k.icon)}</span>
			<span class="yht-kpi-label">${k.label}</span>
		</div>
		<div class="yht-kpi-value">${k.value}</div>
	</div>`;
}

//: Item 11 — "keep direct new create button all the transaction module".
//: Branch users are pinned to this page and never see a desk workspace, so the
//: workspace shortcuts added for Accounts/Buying/Selling do not reach them. The
//: tile keeps opening the list; the + goes straight to a blank document.
//:
//: Only on tiles the role can actually create. Item is read-only for a branch
//: user, so a + there would route them into a permission error.
const CAN_CREATE = [
	"Quotation",
	"Sales Order",
	"Delivery Note",
	"Sales Invoice",
	"Purchase Receipt",
	"Purchase Invoice",
	"Payment Entry",
	"Customer",
];

function action_card(a) {
	// A dialog tile carries no route. It still renders as an anchor so it inherits
	// the card styling and keyboard focus; the click is intercepted below.
	if (a.dialog) {
		return card("#", a.icon, __(a.label), __(a.desc), `data-yht-dialog="${a.dialog}"`);
	}
	const slug = frappe.router.slug(a.doctype);
	const route = a.mode === "new" ? `/app/${slug}/new` : `/app/${slug}`;
	const plus = CAN_CREATE.includes(a.doctype) && a.mode !== "new"
		? `<a class="yht-card-new" href="/app/${slug}/new" title="${__("New")}"
		     aria-label="${__("New {0}", [__(a.doctype)])}">+</a>`
		: "";
	return card(route, a.icon, __(a.label), __(a.desc), "", plus);
}

function report_card(r) {
	return card(
		`/app/query-report/${encodeURIComponent(r.report)}`,
		r.icon,
		__(r.label),
		__(r.desc)
	);
}

function card(route, icon_name, label, desc, attrs = "", extra = "") {
	// `extra` is rendered OUTSIDE the anchor's text span but inside the wrapper, so
	// the + is its own link rather than a nested <a> (which the browser drops).
	if (extra) {
		return `<span class="yht-card-wrap">${card(route, icon_name, label, desc, attrs)}${extra}</span>`;
	}
	return `<a class="yht-card" href="${route}" ${attrs}>
		<span class="yht-card-icon">${icon(icon_name)}</span>
		<span class="yht-card-text">
			<span class="yht-card-title">${frappe.utils.escape_html(label)}</span>
			<span class="yht-card-desc">${frappe.utils.escape_html(desc)}</span>
		</span>
	</a>`;
}

function pending_section(groups, money) {
	const live = groups.filter((g) => g.rows && g.rows.length);
	if (!live.length) return "";

	const columns = live
		.map((group) => {
			const rows = group.rows
				.map((row) => {
					const overdue =
						row.due_date && row.due_date < frappe.datetime.get_today() ? " yht-overdue" : "";
					return `<div class="yht-pending-item${overdue}">
						<div class="yht-pending-main">
							<a href="/app/${frappe.router.slug(group.doctype)}/${encodeURIComponent(row.name)}">
								${frappe.utils.escape_html(row.name)}</a>
							<div class="yht-pending-party">${frappe.utils.escape_html(row.party || "")}</div>
						</div>
						<div class="yht-pending-meta">
							<div class="yht-pending-amount">${money(row.amount)}</div>
							<div class="yht-pending-date">${
								row.date ? frappe.datetime.str_to_user(row.date) : ""
							}</div>
						</div>
					</div>`;
				})
				.join("");

			const more =
				group.total > group.rows.length
					? `<a class="yht-pending-more" href="/app/${frappe.router.slug(group.doctype)}">${__(
							"{0} more",
							[group.total - group.rows.length]
					  )}</a>`
					: "";

			return `<div class="yht-pending-col">
				<div class="yht-pending-head">
					${frappe.utils.escape_html(__(group.label))}
					<span class="yht-pending-count">${group.total}</span>
				</div>
				<div class="yht-pending-list">${rows}${more}</div>
			</div>`;
		})
		.join("");

	return `<h3 class="yht-section">${__("Needs Attention")}</h3>
		<div class="yht-pending-row">${columns}</div>`;
}

// ------------------------------------------------------------------ formatting
//
// KPI values are abbreviated because the full figure does not fit at 32px and a
// wrapped number reads as two numbers. The exact amount stays available in the
// underlying list and in the Needs Attention panel below.

function short_number(value) {
	const num = flt(value);
	if (!num) return "0";
	const abs = Math.abs(num);
	const sign = num < 0 ? "-" : "";
	if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)}M`;
	if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(abs >= 1e5 ? 0 : 1)}K`;
	return `${sign}${abs.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
