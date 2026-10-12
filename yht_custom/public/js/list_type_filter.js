// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Row 27 (meeting 2026-10-11) — ONE "Type" dropdown on the transaction lists.
//
//   Sales Invoice    Sales Invoice · Sales Return
//   Delivery Note    Delivery Note · Delivery Note Return
//   Purchase Invoice Purchase Invoice · Purchase Return · Expense Invoice
//   Purchase Receipt Purchase Receipt · Purchase Receipt Return
//
// Blank = everything, as Osaid asked ("if neither is clicked, show all of them").
// Payment Entry needs nothing: `payment_type` (Pay / Receive / Internal Transfer) is
// a native standard filter.
//
// WHY A VIRTUAL CONTROL AND NOT THE `is_return` CHECK THAT ALREADY SITS IN THE FILTER
// ROW. A standard-filter Check can only say "returns only" — an unticked box adds no
// filter at all (`get_standard_filters` skips a falsy value), so "normal documents
// only" cannot be expressed. This control maps each choice to real column filters and
// feeds them through `filter_area.get_standard_filters`, so the list, its count, the
// saved view and the report view all see ordinary `[doctype, field, "=", value]`
// filters. The native Is Return / Is Expense Invoice checks are hidden, not removed:
// they keep working underneath for a saved view that already carries them.
//
// Loaded from `doctype_list_js`, never `app_include_js` (gotcha 59): erpnext's own
// list JS assigns `frappe.listview_settings[X]` wholesale AFTER boot, so this file
// MERGES `onload` and runs again each time a list bundle is fetched. The IIFE is
// there because one file is evaluated in global scope once per doctype opened.
(function () {
	const FEATURE = "oct11_r27_type_filter";
	if (((frappe.boot && frappe.boot.yht_features) || []).indexOf(FEATURE) === -1) return;

	// label, then the column filters it stands for.
	const KINDS = {
		"Sales Invoice": [
			[__("Sales Invoice"), [["is_return", "=", 0]]],
			[__("Sales Return"), [["is_return", "=", 1]]],
		],
		"Delivery Note": [
			[__("Delivery Note"), [["is_return", "=", 0]]],
			[__("Delivery Note Return"), [["is_return", "=", 1]]],
		],
		"Purchase Invoice": [
			[__("Purchase Invoice"), [["is_return", "=", 0], ["custom_is_expense_invoice", "=", 0]]],
			[__("Purchase Return"), [["is_return", "=", 1]]],
			[__("Expense Invoice"), [["custom_is_expense_invoice", "=", 1]]],
		],
		"Purchase Receipt": [
			[__("Purchase Receipt"), [["is_return", "=", 0]]],
			[__("Purchase Receipt Return"), [["is_return", "=", 1]]],
		],
	};
	const NATIVE = ["is_return", "custom_is_expense_invoice"];
	const FIELDNAME = "yht_kind";

	function install(listview, doctype) {
		const area = listview.filter_area;
		if (!area || !listview.page || !area.standard_filters_wrapper) return;
		if (listview.page.fields_dict[FIELDNAME]) return;

		const kinds = KINDS[doctype];
		const options = [{ value: "", label: "" }].concat(
			kinds.map((kind, index) => ({ value: String(index + 1), label: kind[0] }))
		);
		const field = listview.page.add_field(
			{
				fieldtype: "Select",
				fieldname: FIELDNAME,
				label: __("Type"),
				options: options,
				onchange: () => area.debounced_refresh_list_view(),
			},
			area.standard_filters_wrapper
		);
		// First in the row: it is the question people ask of these lists.
		$(field.wrapper).closest(".form-group").prependTo(area.standard_filters_wrapper);

		NATIVE.forEach((name) => {
			const native = listview.page.fields_dict[name];
			if (native) $(native.wrapper).closest(".form-group").hide();
		});

		const original = area.get_standard_filters.bind(area);
		area.get_standard_filters = function () {
			const filters = original().filter((f) => f[1] !== FIELDNAME);
			const chosen = listview.page.fields_dict[FIELDNAME];
			const index = cint(chosen && chosen.get_value());
			if (index > 0 && kinds[index - 1]) {
				kinds[index - 1][1].forEach((c) => filters.push([doctype, c[0], c[1], c[2]]));
			}
			return filters;
		};
	}

	frappe.provide("frappe.listview_settings");
	Object.keys(KINDS).forEach((doctype) => {
		frappe.provide(`frappe.listview_settings.${doctype}`);
		const settings = frappe.listview_settings[doctype];
		if (settings.__yht_kind) return;
		settings.__yht_kind = true;

		const previous = settings.onload;
		settings.onload = function (listview) {
			if (previous) previous.call(this, listview);
			try {
				install(listview, doctype);
			} catch (e) {
				// A list that cannot show this dropdown must still open.
				console.error("yht type filter", e); // eslint-disable-line no-console
			}
		};
	});
})();
