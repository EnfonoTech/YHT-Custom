// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Row 40 (meeting 2026-10-15) — Payment Entry: once a Mode of Payment is chosen, the account it
// filled in is read-only.
//
// Client, in the meeting: staff choose "Al Rajhi" and then change the account to Cash by hand. The
// account on OUR side — `paid_from` when paying, `paid_to` when receiving — must stay what the
// Mode of Payment says, for every user. The other side is the party's account and is not touched,
// nor is an Internal Transfer. A Mode with no account for the company leaves the field editable,
// because there would be nothing to fall back on.
//
// 🔴 THE SAME FILE CLOSES THE BANK ACCOUNT ERROR SEEN IN THE MEETING. Filling `paid_from` / `paid_to`
// runs ERPNext's `set_company_bank_account`, which reads the matching Bank Account record to fill
// `bank_account`. A branch user cannot read Bank Account (it holds account numbers and IBANs), so
// choosing a Mode of Payment threw "no permission for Bank Account" — and the quick fix, granting
// Bank Account read/write/create to Branch User, hands every branch user every IBAN. The lookup is
// not needed to post anything, so for a user who cannot read Bank Account it is skipped instead.
//
// Inert unless the site has `oct15_r40_pe_account_lock` on.

frappe.provide("yht_custom.pe");

yht_custom.pe.on = function () {
	return ((frappe.boot && frappe.boot.yht_features) || []).indexOf("oct15_r40_pe_account_lock") !== -1;
};

// The side of the entry that is OUR account, for the payment type; "" when neither is.
yht_custom.pe.own_field = function (frm) {
	if (frm.doc.payment_type === "Pay") return "paid_from";
	if (frm.doc.payment_type === "Receive") return "paid_to";
	return "";
};

yht_custom.pe.lock = function (frm) {
	if (!yht_custom.pe.on() || !frm.doc || cint(frm.doc.docstatus) !== 0) return;
	frm.__yht_pe_locked = frm.__yht_pe_locked || {};

	const own = yht_custom.pe.own_field(frm);
	["paid_from", "paid_to"].forEach((fieldname) => {
		const should_lock = !!own && fieldname === own && !!frm.doc.mode_of_payment && !!frm.doc[fieldname];
		if (should_lock) {
			frm.__yht_pe_locked[fieldname] = true;
			frm.set_df_property(fieldname, "read_only", 1);
		} else if (frm.__yht_pe_locked[fieldname]) {
			// Only undo what this file did, so the doctype's own read-only rules are never overridden.
			frm.__yht_pe_locked[fieldname] = false;
			frm.set_df_property(fieldname, "read_only", 0);
		}
	});
};

// ERPNext calls `frm.events.set_company_bank_account(frm)` from its `paid_from` and `paid_to`
// handlers; replacing the entry on `frm.events` is what stops it for this form only.
yht_custom.pe.skip_bank_account_lookup = function (frm) {
	if (!yht_custom.pe.on() || frappe.model.can_read("Bank Account")) return;
	if (frm.events && frm.events.set_company_bank_account && !frm.events.set_company_bank_account.__yht_pe) {
		const skip = function () {};
		skip.__yht_pe = true;
		frm.events.set_company_bank_account = skip;
	}
};

frappe.ui.form.on("Payment Entry", {
	setup(frm) {
		yht_custom.pe.skip_bank_account_lookup(frm);
	},
	onload(frm) {
		yht_custom.pe.skip_bank_account_lookup(frm);
	},
	refresh(frm) {
		yht_custom.pe.skip_bank_account_lookup(frm);
		yht_custom.pe.lock(frm);
	},
	mode_of_payment(frm) {
		yht_custom.pe.lock(frm);
	},
	payment_type(frm) {
		yht_custom.pe.lock(frm);
	},
	paid_from(frm) {
		yht_custom.pe.lock(frm);
	},
	paid_to(frm) {
		yht_custom.pe.lock(frm);
	},
});
