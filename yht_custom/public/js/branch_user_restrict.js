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
// So a branch user who opened a list had no way back except the browser button.
// This adds a persistent navbar item. It lives in the navbar rather than the page
// head because the navbar survives route changes; a page-head button has to be
// re-added on every render and disappears mid-navigation.
function add_dashboard_link() {
	const insert = () => {
		const $navbar = $(".navbar .navbar-nav").first();
		if (!$navbar.length) return false;
		if ($navbar.find(".yht-nav-home").length) return true;

		const $item = $(`
			<li class="nav-item yht-nav-home">
				<a href="/app/yht-dashboard" title="${__("Branch Dashboard")}">
					${frappe.utils.icon("dashboard", "sm")}
					<span>${__("Dashboard")}</span>
				</a>
			</li>
		`);
		// Let frappe's router handle it rather than a full page load.
		$item.find("a").on("click", function (e) {
			e.preventDefault();
			frappe.set_route("yht-dashboard");
		});
		$navbar.prepend($item);
		return true;
	};

	if (insert()) return;
	// The navbar can mount after app_ready; retry briefly rather than give up.
	let tries = 0;
	const timer = setInterval(() => {
		if (insert() || ++tries > 20) clearInterval(timer);
	}, 250);
}
