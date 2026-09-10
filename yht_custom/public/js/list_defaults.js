// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Client sheet item 35 — a transaction list opens on the current fiscal year.
//
// 🔴 LOADED FROM `doctype_list_js`, NOT `app_include_js`, AND THAT IS THE WHOLE
// TRICK. erpnext's own list JS opens with a WHOLESALE assignment to
// `frappe.listview_settings["X"]`, and a doctype's list bundle is fetched when
// the list is first opened — long after `app_include_js` has run. Anything
// merged in at boot is discarded silently: no error, the default simply never
// applies. `frappe/desk/form/meta.py` adds the doctype's own `<doctype>_list.js`
// first and THEN concatenates the `doctype_list_js` hook file, so a merge from
// here lands after erpnext's assignment and survives.
//
// Which is also why this file only ever MERGES. It never assigns that key.
//
// ⚠️ WRAPPED IN AN IIFE ON PURPOSE. One file is registered under eight
// doctypes and the desk evaluates each doctype's list JS in global scope, so a
// top-level `const` would throw "Identifier has already been declared" the
// second time a user opens one of these lists in a session.
(function () {
	// The eight doctypes that carry `custom_fiscal_year` — the same set as
	// `yht_custom.fiscal_year.DATE_FIELD`, which is what hooks.py registers this
	// file under.
	const LISTS = [
		"Sales Invoice",
		"Purchase Invoice",
		"Delivery Note",
		"Purchase Receipt",
		"Payment Entry",
		"Journal Entry",
		"Sales Order",
		"Quotation",
	];
	const FIELD = "custom_fiscal_year";

	// Resolved server-side in `boot.boot_session` because `setup_defaults()`
	// builds the list synchronously — there is no moment to fetch it in. An
	// empty value means no Fiscal Year covers today, and then no filter is set
	// at all rather than one naming a year that does not exist.
	if (!frappe.boot.yht_current_fiscal_year) return;

	frappe.provide("frappe.listview_settings");

	for (const doctype of LISTS) {
		frappe.provide(`frappe.listview_settings.${doctype}`);
		const settings = frappe.listview_settings[doctype];

		const existing = Array.isArray(settings.filters) ? settings.filters : [];
		// Appended, not replaced: a doctype's own list JS may already ship a
		// default filter, and dropping it here would be a silent regression.
		// Guarded because this file runs again every time one of the eight lists
		// is opened for the first time in a session.
		if (existing.some((f) => Array.isArray(f) && f.indexOf(FIELD) !== -1)) continue;

		settings.filters = existing.concat([[FIELD, "=", frappe.boot.yht_current_fiscal_year]]);

		// 🔴 `settings.filters` ALONE REACHES ALMOST NOBODY, AND THAT IS NOT
		// OBVIOUS. `list_view.js::setup_defaults` reads it at Priority 2 only:
		//
		//     if (Array.isArray(this.view_user_settings.filters))  // Priority 1
		//         this.filters = this.validate_filters(saved_filters);
		//     else                                                 // Priority 2
		//         this.filters = (this.settings.filters || []).map(...)
		//
		// `Array.isArray([])` is TRUE. Opening a list once saves a filters array —
		// usually an EMPTY one — and from then on Priority 1 wins with nothing in
		// it, so the default never applies again. Measured on the client site:
		// 591 saved list settings across these eight doctypes, 92 distinct users.
		// Shipping only the line above would have been a feature that quietly
		// does nothing for every person who has ever used the system.
		//
		// `onload` runs after `setup_defaults` and before the first `refresh()`
		// (list_view.js:333, then :341), so assigning here is picked up by the
		// initial fetch — no second query, no visible re-filter.
		//
		// It applies ONLY when nothing else is filtering. A saved filter, a
		// filter in the route, or one the doctype's own list JS set is left
		// alone: the year is a default, not a policy.
		const prior = settings.onload;
		settings.onload = function (listview) {
			if (prior) prior(listview);
			if (!frappe.boot.yht_current_fiscal_year) return;
			if (listview.filters && listview.filters.length) return;
			listview.filters = [
				[listview.doctype, FIELD, "=", frappe.boot.yht_current_fiscal_year],
			];
		};
	}
})();
