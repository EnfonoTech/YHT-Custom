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

const ALLOWED_ROUTES = ["yht-dashboard", "query-report", "report", "print", "form", "dashboard-view"];

$(document).on("app_ready", function () {
	if (!frappe.boot || !frappe.boot.yht_branch_restricted) return;

	add_dashboard_link();

	frappe.router.on("change", () => {
		const route = frappe.get_route();
		if (!route || !route.length) return;

		const [kind, target] = route;

		if (kind === "List" || kind === "Form" || kind === "Tree") {
			if (target && !ALLOWED_DOCTYPES.includes(target)) {
				frappe.show_alert(
					{ message: __("{0} is not available for your role.", [__(target)]), indicator: "orange" },
					5
				);
				frappe.set_route("yht-dashboard");
			}
			return;
		}

		if (kind === "Workspaces" && target && target !== "Branch User") {
			frappe.set_route("yht-dashboard");
		}
	});
});


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

		const $item = $(`
			<li class="nav-item yht-nav-home">
				<a href="/app/${DASHBOARD_ROUTE}" title="${__("Branch Dashboard")}">
					<span class="yht-nav-arrow">&larr;</span>
					<span>${__("Dashboard")}</span>
				</a>
			</li>
		`);
		// Let frappe's router handle it rather than a full page load.
		$item.find("a").on("click", function (e) {
			e.preventDefault();
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
