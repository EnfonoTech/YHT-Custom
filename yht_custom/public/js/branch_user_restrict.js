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
