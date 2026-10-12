// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Row 37 (meeting 2026-10-11) — the Print Heading fills itself in as the document is
// made, so the operator SEES "Delivery Note" turn into "Delivery Note Return" when they
// tick Is Return, instead of finding out on the printout.
//
// The field (`select_print_heading`) is STANDARD and already `allow_on_submit`; the
// server moves it onto the front page (`meeting_1011.setup_heading_front`) and
// `print_heading.boot_map()` says which heading each document opens with. Both are
// empty unless `oct11_r37_print_heading_front` is on for the site, and then this file
// does nothing at all.
//
// 🔴 IT ONLY EVER REPLACES A HEADING IT COULD HAVE PUT THERE ITSELF. A blank field, or
// one of this doctype's own two defaults, is filled; anything else is a decision
// somebody made — the whole point of CR-005 is that the choice can be corrected in bulk
// afterwards — and is left alone. Drafts only: a submitted document's heading is changed
// by hand, never by a refresh.
//
// One file under four doctypes, so the registration is guarded (see katc_print_buttons.js).

frappe.provide("yht_custom.print_heading_front");

(function () {
	if (yht_custom.print_heading_front.bound) return;
	yht_custom.print_heading_front.bound = true;

	const FIELD = "select_print_heading";
	const map = (frappe.boot && frappe.boot.yht_print_headings) || {};

	function defaults_of(doctype) {
		const entry = map[doctype] || {};
		return [entry.fwd, entry.ret].filter(Boolean);
	}

	function wanted(frm) {
		const entry = map[frm.doctype] || {};
		return (cint(frm.doc.is_return) && entry.ret) || entry.fwd || "";
	}

	function apply(frm) {
		if (!map[frm.doctype] || !frm.doc || frm.doc.docstatus !== 0) return;
		if (!frm.fields_dict[FIELD]) return;
		const current = frm.doc[FIELD] || "";
		if (current && defaults_of(frm.doctype).indexOf(current) === -1) return;
		const heading = wanted(frm);
		if (heading && heading !== current) {
			frm.set_value(FIELD, heading);
		}
	}

	Object.keys(map).forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				// A NEW document only: filling a blank heading on every refresh of an old
				// draft would mark it "Not Saved" the moment it is opened.
				if (frm.is_new()) apply(frm);
			},
			is_return(frm) {
				apply(frm);
			},
		});
	});
})();
