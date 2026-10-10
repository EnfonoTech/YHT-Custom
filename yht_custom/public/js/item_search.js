// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

// Rows 7 + 14 of the 2026-10-08 sheet — point every Item picker at
// `yht_custom.item_search.item_query`.
//
// 🔴 WHY THIS FILE EXISTS WHEN hooks.py ALREADY OVERRIDES THE METHOD.
// `override_whitelisted_methods` is honoured in exactly four places in frappe
// 15.118 — `handler.execute_cmd`, `api/v2`, `model/mapper` and `desk/treeview`.
// The Link picker is none of them: `link.js` POSTs `frappe.desk.search.search_link`
// with `query = "erpnext.controllers.queries.item_query"`, and `search_widget`
// resolves that string with `frappe.get_attr` + `frappe.call`, which never look
// at the hook. Measured on yht-test 2026-10-10 with the override registered:
// "elbow 1" through search_link returned 0 rows — upstream's whole-string LIKE —
// and the dropdown showed nothing but "Create a new Item".
//
// So the name has to change on the client, in the ONE place every Link control
// builds its request: `ControlLink.set_custom_query(args)`. Item grids on every
// transaction, dialogs and Dynamic Links all go through it. The hooks.py entry
// stays for a direct `/api/method/erpnext.controllers.queries.item_query` call.
//
// Gated on the site's boot switches so the live site keeps sending upstream's
// name; the server function ALSO falls through to ERPNext while the switch is
// off, so both halves have to be on for anything to change.

(function () {
	const UPSTREAM = "erpnext.controllers.queries.item_query";
	const OURS = "yht_custom.item_search.item_query";
	const SWITCH = "oct08_r07_item_search";

	function yht_r07_on() {
		return ((frappe.boot && frappe.boot.yht_features) || []).includes(SWITCH);
	}

	const control = frappe.ui && frappe.ui.form && frappe.ui.form.ControlLink;
	const proto = control && control.prototype;
	if (!proto || typeof proto.set_custom_query !== "function" || proto.set_custom_query.__yht_r07) {
		return;
	}

	const upstream_set_custom_query = proto.set_custom_query;

	function set_custom_query(args) {
		const out = upstream_set_custom_query.apply(this, arguments);
		if (args && args.query === UPSTREAM && yht_r07_on()) {
			args.query = OURS;
		}
		return out;
	}
	set_custom_query.__yht_r07 = true;
	proto.set_custom_query = set_custom_query;
})();
