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
// 🔴 CR-004 — TWO BUTTONS, ONE FORMAT PER DOCTYPE.
//
// Before this there were four on Quotation and Sales Order — Print PDF, Print with
// Arabic, Proforma Invoice, Print Without LH — each naming its own Print Format
// record. That IS the thing the client asked to stop: "don't make a separate print
// format for each one, give it as a tick option".
//
// The other two axes moved to where the desk already puts them:
//
//   Arabic     the print dialog's Language selector. `yht_print_lang()` reads
//              `frappe.local.lang` inside the shared template.
//   Proforma   `Print As` on the document; `KATC Quotation` / `KATC Sales Order`
//              route to the proforma template when it says so.
//
// So the buttons keep only the axis a button is genuinely better at: the one-click
// with-or-without-letterhead pair the client uses all day. Anything else is two
// clicks away in the print dialog, which is where a tick option belongs.
//
// ⚠️ THE OLD TABLE IS STILL HERE, under the switch. This file is served to the
// client's live site the moment it is pulled, and `KATC Quotation Arabic` and the
// rest are only disabled on a site that has run the migrate — so where the switch
// is off, the four buttons must keep naming formats that still exist.
const KATC_BUTTONS_LEGACY = {
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

//: doctype → its ONE format. Purchase Order joins the list here (CR-021), which is
//: what "follows the CR-004 architecture once it lands" meant.
const KATC_FORMAT = {
	"Delivery Note": "KATC Delivery Note",
	"Sales Invoice": "KATC Tax Invoice",
	"Sales Order": "KATC Sales Order",
	Quotation: "KATC Quotation",
	"Purchase Order": "KATC Purchase Order",
};

const KATC_BUTTONS_CONSOLIDATED = {};
Object.keys(KATC_FORMAT).forEach((doctype) => {
	KATC_BUTTONS_CONSOLIDATED[doctype] = [
		{ label: __("Print"), format: KATC_FORMAT[doctype], no_letterhead: 0, letterhead: KATC_LETTER_HEAD },
		{ label: __("Print Without LH"), format: KATC_FORMAT[doctype], no_letterhead: 1 },
	];
});

function katc_consolidated() {
	return (
		((frappe.boot && frappe.boot.yht_features) || []).indexOf("cr_004_print_heading") !== -1
	);
}

function katc_buttons_for(doctype) {
	const table = katc_consolidated() ? KATC_BUTTONS_CONSOLIDATED : KATC_BUTTONS_LEGACY;
	return table[doctype] || [];
}


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
	// 🔴 NEVER SHOW A BUTTON THE USER CANNOT USE. `download_pdf` enforces
	// `validate_print_permission` server-side, so a button the caller lacks `print`
	// on does not leak anything — it just fails in their face after they click it.
	//
	// Found when CR-021 put these buttons on Purchase Order: measured on yht-test,
	// `Branch User` holds read = 1 and print = 0 there, so every branch operator
	// would have seen two buttons that error. The permission is right — purchasing
	// is not their job — so the buttons yield, not the permission.
	if (!frappe.model.can_print(frm.doc.doctype)) {
		return;
	}

	katc_buttons_for(frm.doc.doctype).forEach((spec) => {
		// Top level, no group argument — the incumbent's buttons sit on the toolbar.
		frm.add_custom_button(spec.label, () => katc_download(frm, spec));
	});
}

// One file registered under four doctypes is loaded once per doctype visited in a
// session. Registering all four handlers unconditionally would stack them up, and
// the buttons would duplicate for anyone who opened more than one of the four.
if (!yht_custom.katc_prints.bound) {
	yht_custom.katc_prints.bound = true;
	Object.keys(Object.assign({}, KATC_BUTTONS_LEGACY, KATC_BUTTONS_CONSOLIDATED)).forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				katc_add_buttons(frm);
			},
		});
	});
}
