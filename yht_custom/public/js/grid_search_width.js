// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

// CR-018 — turn the wide grid-search dropdown on for THIS SITE.
//
// The whole of the change is CSS (`public/css/yht_custom.css`, "CR-018"). This
// file exists only because a stylesheet cannot read `site_config.json`, and this
// bench serves the client's live site and UAT out of one `apps/yht_custom` — so
// the rule is scoped to `body.yht-wide-grid-search` and this is what puts the
// class there.
//
// 🔴 `frappe.boot` IS NOT POPULATED WHEN A DESK BUNDLE FIRST EVALUATES. The
// class is therefore written on `app_ready` (and again on `startup`, which fires
// on a soft route change after a `bench clear-cache` reload), rather than at
// import time where `frappe.boot.yht_features` reads undefined and the feature
// silently never appears.

frappe.provide("yht");

yht.grid_search_width = {
	FEATURE: "cr_018_grid_search_width",
	CLASS: "yht-wide-grid-search",

	apply() {
		const on = ((frappe.boot && frappe.boot.yht_features) || []).indexOf(
			yht.grid_search_width.FEATURE
		) !== -1;
		document.body.classList.toggle(yht.grid_search_width.CLASS, on);
	},
};

$(document).on("app_ready startup", () => yht.grid_search_width.apply());
