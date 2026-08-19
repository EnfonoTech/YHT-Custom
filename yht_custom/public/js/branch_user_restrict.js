// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Navigation whitelist for restricted branch users.
//
// This is a USABILITY guard, not a security boundary. Real enforcement is
// server-side: Custom DocPerm decides what a user may open at all, and
// permission_query_conditions decides which rows they see. This only stops a
// restricted user wandering into a list they have no business in and meeting a
// bare permission error.
//
// KEEP IN SYNC with the tiles in yht_dashboard.js — a tile pointing at a doctype
// missing from this list bounces the user straight back to the dashboard.

frappe.provide("yht_custom");

const ALLOWED_DOCTYPES = [
	"Quotation",
	"Sales Order",
	"Delivery Note",
	"Sales Invoice",
	"Purchase Receipt",
	"Purchase Invoice",
	"Payment Entry",
	"Customer",
	"Address",
	"Contact",
	"Item",
];

//: Single-segment routes a branch user legitimately lands on. Multi-segment routes
//: (["query-report", "Stock Balance"], ["print", ...]) are handled by the branches below and
//: do not need to appear here — but leaving them costs nothing and documents the intent.
//:
//: This list is now LOAD-BEARING: anything absent from it that arrives as a lone slug is
//: treated as a doctype the role cannot open. Add a page here before linking a branch user
//: to it, or they will be bounced off it.
const ALLOWED_ROUTES = [
	"yht-dashboard",
	"query-report",
	"report",
	"print",
	"form",
	"dashboard-view",
	"workspace",
	"Workspaces",
];

// ── redirect BEFORE frappe's router sees the URL ─────────────────────────────
//
// Bouncing from app_ready is too late. On a direct load of /app/asset the router still
// resolves the route first, fails, and raises its own modal:
//
//     Not found — Page asset not found — The resource you are looking for is not available
//
// So the user landed on the dashboard WITH an error dialog on top of it, which is uglier than
// the bare permission error it replaced and contradicts the orange-message behaviour the
// training material describes.
//
// This file is loaded via app_include_js, which runs after frappe.boot is on the page but
// before the desk boots the router. Rewriting the URL here means the router only ever sees
// the dashboard route, so no not-found dialog is ever raised. The app_ready gate below still
// covers in-app navigation, where the router is already running.
(function redirect_before_boot() {
	if (typeof frappe === "undefined" || !frappe.boot || !frappe.boot.yht_branch_restricted) return;
	const match = /^\/app\/([^/?#]+)/.exec(window.location.pathname);
	if (!match) return;

	const slug = match[1];
	if (ALLOWED_ROUTES.includes(slug)) return;
	// A slug that IS an allowed doctype is fine — /app/sales-invoice is a real destination.
	if (ALLOWED_DOCTYPES.some((dt) => frappe.router && frappe.router.slug(dt) === slug)) return;

	window.history.replaceState(null, "", "/app/yht-dashboard");
	// Tell the user why, once the desk is up enough to show it.
	$(document).on("app_ready", function () {
		frappe.show_alert(
			{
				message: __("{0} is not available for your role.", [__(frappe.model.unscrub(slug))]),
				indicator: "orange",
			},
			6
		);
	});
})();

$(document).on("app_ready", function () {
	if (!frappe.boot || !frappe.boot.yht_branch_restricted) return;

	add_dashboard_link();

	// Check the route we ARRIVED on, then every route change after it.
	//
	// `router.on("change")` alone was not enough, and the dry-run caught it: navigating
	// straight to /app/asset landed there and stayed. The handler is registered during
	// app_ready, by which time the FIRST route has already been resolved — no "change"
	// event ever fires for it. So a typed URL, a bookmark, or simply refreshing the page
	// while on a disallowed doctype walked right past the gate and the user met a bare
	// "Not permitted" instead of being sent home.
	enforce_route();
	frappe.router.on("change", enforce_route);
});

function enforce_route() {
	const route = frappe.get_route();
	if (!route || !route.length) return;

	const [kind, target] = route;

	// ── the single-slug case ────────────────────────────────────────────────────
	//
	// MEASURED, because two earlier guesses at this were wrong. On a DIRECT URL load
	// frappe.get_route() returns different shapes depending on whether the user may read
	// the doctype:
	//
	//   /app/sales-invoice   (permitted)      -> ["List", "Sales Invoice", "List"]
	//   /app/asset           (NOT permitted)  -> ["asset"]
	//   /app/yht-dashboard   (a page)         -> ["yht-dashboard"]
	//
	// The router cannot expand a doctype whose meta it is not allowed to load, so it
	// leaves the raw slug in place — and it stays that way, still ["asset"] five seconds
	// later, so waiting for it to settle does not help either.
	//
	// That makes an unexpanded lone slug the permission denial itself. Anything not in
	// ALLOWED_ROUTES is therefore a doctype this role cannot open, and gets sent home with
	// the doctype named rather than left on a bare "Not permitted".
	if (route.length === 1) {
		const slug = route[0];
		if (ALLOWED_ROUTES.includes(slug)) return;
		bounce(frappe.model.unscrub(slug));
		return;
	}

	if (kind === "List" || kind === "Form" || kind === "Tree") {
		if (target && !ALLOWED_DOCTYPES.includes(target)) bounce(target);
		return;
	}

	if (kind === "Workspaces" && target && target !== "Branch User") {
		frappe.set_route("yht-dashboard");
	}
}

function bounce(label) {
	frappe.show_alert(
		{ message: __("{0} is not available for your role.", [__(label)]), indicator: "orange" },
		5
	);
	frappe.set_route("yht-dashboard");
}

// A way back to the dashboard, on every page.
//
// WHY THIS IS NEEDED: `role_home_page` is only consulted by
// frappe/website/utils.py::get_home_page_via_hooks, which runs for WEBSITE users.
// For a desk System User, frappe/auth.py sets the post-login home_page from
// get_default_path() or "/app" — so our hook never applies, the desk lands on the
// first allowed workspace, and clicking the logo does NOT return to the dashboard.
// boot.py's `default_route` covers the initial load only.
//
// WHY IT DISAPPEARED THE FIRST TIME — do not reintroduce this:
// the previous version inserted into `$(".navbar .navbar-nav").first()`. There are
// TWO `.navbar-nav` lists in frappe's navbar.html, and the FIRST one is
//     <ul class="nav navbar-nav d-none d-sm-flex" id="navbar-breadcrumbs">   (line 11)
// which frappe EMPTIES AND REBUILDS on every route change. So the button survived
// on the dashboard (no breadcrumbs there) and vanished the moment the user opened
// any list — exactly the symptom reported. The persistent list is the second one,
// inside `.navbar-collapse` (line 37), holding notifications / help / avatar.
//
// Two affordances, because operators reach for both:
//   1. an explicit "Dashboard" item in the persistent navbar list
//   2. the logo itself, repointed from /app to the dashboard

const DASHBOARD_ROUTE = "yht-dashboard";

function add_dashboard_link() {
	const insert = () => {
		// NOT .first() — that is #navbar-breadcrumbs, which gets wiped per route.
		const $navbar = $(".navbar .navbar-collapse .navbar-nav").first();
		if (!$navbar.length) return false;
		if ($navbar.find(".yht-nav-home").length) return true;

		// MARKUP MATTERS — this is `li.nav-item > button.nav-link`, deliberately the
		// same shape as the notifications and Help items in frappe's navbar.html.
		//
		// The first version used `li > a`, and on this bench it rendered dark-on-dark
		// and was effectively invisible. grey_theme colours navbar items with
		//     .navbar .nav-item button.nav-link { color: var(--btn-default-hover-bg) !important }
		// i.e. it targets BUTTONS. Its anchor rule, `.navbar .navbar-expand li a`, is a
		// dead selector — `navbar-expand` sits on the SAME element as `navbar`
		// (`<header class="navbar navbar-expand">`), never a descendant — so nothing
		// styled the anchor, and our own `var(--navbar-text-color, var(--text-color))`
		// fell through to the dark body text colour on a #4a5464 navbar.
		//
		// Matching the shape frappe and the theme already style means the item
		// inherits the right colour under grey_theme AND under stock frappe's white
		// navbar, with no colour of our own to keep in sync.
		const $item = $(`
			<li class="nav-item yht-nav-home">
				<button class="btn-reset nav-link" title="${__("Branch Dashboard")}">
					<span class="yht-nav-arrow">&larr;</span>
					<span>${__("Dashboard")}</span>
				</button>
			</li>
		`);
		$item.find("button").on("click", function () {
			frappe.set_route(DASHBOARD_ROUTE);
		});
		$navbar.prepend($item);
		return true;
	};

	const point_logo_home = () => {
		const $brand = $(".navbar .navbar-brand.navbar-home");
		if (!$brand.length || $brand.data("yht-rebound")) return;
		$brand.data("yht-rebound", true).attr("href", `/app/${DASHBOARD_ROUTE}`);
		$brand.on("click", function (e) {
			e.preventDefault();
			frappe.set_route(DASHBOARD_ROUTE);
		});
	};

	const apply = () => {
		point_logo_home();
		return insert();
	};

	// Re-assert on every route change. The target list is persistent, so this is
	// normally a no-op — but it is cheap, idempotent (the .yht-nav-home guard) and
	// it means a future frappe change to the navbar cannot silently remove the only
	// way a restricted user has of getting back.
	frappe.router.on("change", apply);

	if (apply()) return;
	// The navbar can mount after app_ready; retry briefly rather than give up.
	let tries = 0;
	const timer = setInterval(() => {
		if (apply() || ++tries > 20) clearInterval(timer);
	}, 250);
}
