// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

/**
 * The client's incumbent print buttons, recreated on this site.
 *
 * Registered through `doctype_js` rather than `app_include_js`: it takes effect
 * without a `bench build`, and builds are limited to the maintenance window.
 *
 * WHY `download_pdf` AND NOT `/printview?trigger_print=1`. The artefacts' footer
 * reads `Page 1 of 1`. Those spans are only resolved by wkhtmltopdf, which frappe
 * drives with `--footer-html` (see `frappe.utils.pdf.prepare_header_footer`, which
 * lifts `id="footer-html"` out of the rendered page). A browser print dialog
 * leaves them empty.
 *
 * WHY THE WITH-LETTERHEAD BUTTONS PASS `letterhead=` EXPLICITLY. This is not
 * belt-and-braces. `frappe.www.printview.get_letter_head` prefers
 * `doc.letter_head` over the default, and on this site documents carry
 * `letter_head = "KATHOOM ALKHOBAR"` (the incumbent image) or the dangling
 * `"Kathoom without letterhead"` (1,266 of them). Without the explicit argument
 * the new letterhead never appears on a historical document.
 *
 * NOTHING BUT doctype, name, format AND THE TWO FLAGS goes in the query string.
 * `download_pdf` is `@frappe.whitelist(allow_guest=True)` and its real boundary is
 * `validate_print_permission(doc)` inside it. Adding a signing `key=` would turn
 * one of these links into a guest-readable URL for a customer document.
 */

frappe.provide("yht_custom.katc_prints");

// Duplicated from `yht_custom.katc_letterhead.KATC_LETTER_HEAD` because JS cannot
// import Python. A test greps this file and asserts the two strings are equal.
const KATC_LETTER_HEAD = "KATC Letterhead";

// One row per toolbar button, in the order the client asked for them:
// Print → With Arabic → Proforma Invoice → Without LH.
//
// 🔴 SALES INVOICE AND DELIVERY NOTE GET NO ARABIC BUTTON, DELIBERATELY. Both formats
// already print the Arabic item name INSIDE the item cell —
// `{% set ar = yht_item_ar(row) %}{% if ar %}<div class="katc-ar">{{ ar }}</div>{% endif %}`
// — so an "Item Name in Arabic" COLUMN would print it twice. The Arabic column is the
// idiom of one client artefact (quote print 2 with arabic.pdf) and applies only where
// the base format carries no Arabic at all: Quotation and Sales Order.
//
// ⚠️ Print and Without LH now name the SAME format for every doctype. The letterhead is
// the button's job, not the format's — each shared template renders `{{ letter_head }}`
// when one is passed and a measured spacer when `no_letterhead` is set. Before this,
// Sales Order had no with-letterhead plain print at all, because its spacer was
// unconditional.
const KATC_BUTTONS = {
	"Delivery Note": [
		{ label: __("Print PDF"), format: "KATC Delivery Note", no_letterhead: 0, letterhead: KATC_LETTER_HEAD },
		{ label: __("Print Without LH"), format: "KATC Delivery Note", no_letterhead: 1 },
	],
	"Sales Invoice": [
		{ label: __("Print PDF"), format: "KATC Tax Invoice", no_letterhead: 0, letterhead: KATC_LETTER_HEAD },
		{ label: __("Print Without LH"), format: "KATC Tax Invoice", no_letterhead: 1 },
	],
	"Sales Order": [
		{ label: __("Print PDF"), format: "KATC Sales Order", no_letterhead: 0, letterhead: KATC_LETTER_HEAD },
		{ label: __("Print with Arabic"), format: "KATC Sales Order Arabic", no_letterhead: 0, letterhead: KATC_LETTER_HEAD },
		{ label: __("Proforma Invoice"), format: "KATC Proforma Invoice", no_letterhead: 0, letterhead: KATC_LETTER_HEAD },
		{ label: __("Print Without LH"), format: "KATC Sales Order No LH", no_letterhead: 1 },
	],
	Quotation: [
		{ label: __("Print PDF"), format: "KATC Quotation", no_letterhead: 0, letterhead: KATC_LETTER_HEAD },
		{ label: __("Print with Arabic"), format: "KATC Quotation Arabic", no_letterhead: 0, letterhead: KATC_LETTER_HEAD },
		{ label: __("Proforma Invoice"), format: "KATC Quotation Proforma", no_letterhead: 0, letterhead: KATC_LETTER_HEAD },
		{ label: __("Print Without LH"), format: "KATC Quotation No LH", no_letterhead: 1 },
	],
};

function katc_download(frm, spec) {
	const args = {
		doctype: frm.doc.doctype,
		name: frm.doc.name,
		format: spec.format,
		no_letterhead: spec.no_letterhead,
		// `language`, NOT `_lang`. `download_pdf`'s signature is
		// `(doctype, name, format, doc, no_letterhead, language, letterhead)` and the
		// API handler filters `frappe.form_dict` through `get_newargs`, so `_lang`
		// (frappe's own printview toolbar spells it that way) is dropped on the floor
		// and never reaches `print_language()`. The formats' `default_print_language`
		// does NOT cover this: it is read only by Notification and Workflow Action,
		// never on the print/PDF path.
		language: "en",
	};
	if (spec.letterhead) {
		args.letterhead = spec.letterhead;
	}
	const query = Object.keys(args)
		.map((key) => `${encodeURIComponent(key)}=${encodeURIComponent(args[key])}`)
		.join("&");
	window.open(`/api/method/frappe.utils.print_format.download_pdf?${query}`);
}

function katc_add_buttons(frm) {
	if (!frm.doc || frm.is_new()) {
		return;
	}
	(KATC_BUTTONS[frm.doc.doctype] || []).forEach((spec) => {
		// Top level, no group argument — the incumbent's buttons sit on the toolbar.
		frm.add_custom_button(spec.label, () => katc_download(frm, spec));
	});
}

// One file registered under four doctypes is loaded once per doctype visited in a
// session. Registering all four handlers unconditionally would stack them up, and
// the buttons would duplicate for anyone who opened more than one of the four.
if (!yht_custom.katc_prints.bound) {
	yht_custom.katc_prints.bound = true;
	Object.keys(KATC_BUTTONS).forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				katc_add_buttons(frm);
			},
		});
	});
}
