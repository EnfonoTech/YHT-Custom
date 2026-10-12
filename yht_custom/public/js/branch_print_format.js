// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Row 36 (meeting 2026-10-11) — the printer icon opens the BRANCH's default format.
//
// `frappe/printing/page/print/print.js::set_default_print_format` preselects
// `this.frm.meta.default_print_format`, and `frm.meta` is this browser's own copy of
// the DocType — so unlike the server's cached meta it can differ per session. The
// map comes from `yht_custom.branch_print_format.boot_value()` and is empty unless
// the site has `oct11_r36_branch_print_format` on, in which case this file does
// nothing at all.
//
// It only moves the PRESELECTION. A toolbar button that names its format, a direct
// /printview?format= link and an emailed attachment are untouched.

frappe.provide("yht_custom.branch_print_format");

(function () {
	if (yht_custom.branch_print_format.bound) return;
	yht_custom.branch_print_format.bound = true;

	const formats = (frappe.boot && frappe.boot.yht_branch_print_formats) || {};
	Object.keys(formats).forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			setup(frm) {
				if (frm.meta && formats[doctype]) {
					frm.meta.default_print_format = formats[doctype];
				}
			},
		});
	});
})();
