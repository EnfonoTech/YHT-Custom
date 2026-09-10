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

	}
})();
