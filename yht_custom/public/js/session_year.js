// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Row 26 (meeting 2026-10-11) — ask for the fiscal year once after login.
//
// The answer is a Session Default (`fiscal_year`), which frappe clears on logout, so every
// login starts with none chosen and boot says `needs_prompt`. The list default filters then
// follow it (`yht_custom/session_year.py`).
//
// A Select rather than frappe's own Link prompt: a Branch User cannot read Fiscal Year, and
// the stock dialog on the live site would also drag in four other rows. The avatar-menu
// "Session Defaults" item is untouched and still works.
//
// Inert unless the site has `oct11_r26_session_fiscal_year` on and boot asks for the prompt.
// The flag is set BEFORE the dialog is shown, so a dismissed dialog does not return on the
// next route.

frappe.provide("yht_custom.session_year");

yht_custom.session_year.maybe_prompt = function () {
	const features = (frappe.boot && frappe.boot.yht_features) || [];
	if (features.indexOf("oct11_r26_session_fiscal_year") === -1) return;

	const info = (frappe.boot && frappe.boot.yht_session_year) || {};
	if (!info.needs_prompt || !(info.choices || []).length) return;

	// Once per LOGIN, not once per browser tab. `sessionStorage` outlives a logout and the next
	// login in the same tab, so a plain "shown" flag kept the pop-up away from every login after
	// the first (found in the client's UAT round, 2026-10-13: "option popped up once in multiple
	// log-in attempts"). The CSRF token is minted per login session, so the flag holds that token.
	try {
		const login = frappe.csrf_token || (frappe.boot && frappe.boot.sid) || "1";
		if (sessionStorage.getItem("yht_session_year_shown") === login) return;
		sessionStorage.setItem("yht_session_year_shown", login);
	} catch (e) {
		// Storage blocked: prompt anyway, once per page load.
	}

	const companies = info.companies || [];
	const fields = [
		{
			fieldtype: "Select",
			fieldname: "fiscal_year",
			label: __("Fiscal Year"),
			reqd: 1,
			options: info.choices.join("\n"),
			default: info.current || info.choices[0],
		},
	];
	if (companies.length > 1) {
		fields.push({
			fieldtype: "Link",
			fieldname: "company",
			label: __("Company"),
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		});
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Session Defaults"),
		fields: fields,
		primary_action_label: __("Save"),
		primary_action(values) {
			const default_values = { fiscal_year: values.fiscal_year };
			if (values.company) default_values.company = values.company;
			frappe.call({
				method: "frappe.core.doctype.session_default_settings.session_default_settings.set_session_default_values",
				args: { default_values: default_values },
				callback(r) {
					if (r.message === "success") {
						dialog.hide();
						frappe.show_alert({ message: __("Session Defaults Saved"), indicator: "green" });
						// Recomputes boot, which re-syncs the saved list filters to the new year.
						frappe.ui.toolbar.clear_cache();
					} else {
						frappe.show_alert({
							message: __("An error occurred while setting Session Defaults"),
							indicator: "red",
						});
					}
				},
			});
		},
	});
	dialog.show();
};

$(document).on("app_ready", yht_custom.session_year.maybe_prompt);

// A Link field to Fiscal Year takes the user's `fiscal_year` default on a NEW document —
// frappe does that for any such Link. With a Session Default of 2025 a document dated today
// (2026) therefore opened showing "Fiscal Year 2025", under a description saying the value is
// derived from the date on every save. The server does derive it (`fiscal_year.set_fiscal_year`),
// so nothing wrong is stored; but the form said otherwise until the save. Cleared on a new draft,
// only where the site has the switch on. Found by the browser pass, not by a test.
(function () {
	const DOCTYPES = [
		"Sales Invoice", "Purchase Invoice", "Delivery Note", "Purchase Receipt",
		"Payment Entry", "Journal Entry", "Sales Order", "Quotation",
	];
	// Row 26, "new also" (2026-10-15): a NEW document stays inside the chosen fiscal year. The server
	// refuses anything else (`session_year.enforce_new_document_year`); this keeps the operator from
	// reaching that refusal: a default date outside the year is moved to its nearest end, and the
	// date picker only offers the year's own dates. `info.limit` is `null` unless the site has
	// `oct15_r26_new_document_year` on and the user has chosen a year.
	function limit_new_document_dates(frm) {
		const info = (frappe.boot && frappe.boot.yht_session_year) || {};
		const lim = info.limit;
		if (!lim || !frm.is_new()) return;
		const field = (lim.date_fields || {})[frm.doctype];
		if (!field || !frm.fields_dict[field]) return;

		const value = frm.doc[field];
		if (value && (value < lim.start || value > lim.end)) {
			frm.set_value(field, value > lim.end ? lim.end : lim.start);
		}
		const control = frm.fields_dict[field];
		if (control.datepicker && control.datepicker.update) {
			try {
				control.datepicker.update({
					minDate: frappe.datetime.str_to_obj(lim.start),
					maxDate: frappe.datetime.str_to_obj(lim.end),
				});
			} catch (e) {
				// The server rule still holds; only the courtesy is lost.
			}
		}
	}

	DOCTYPES.forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			onload(frm) {
				const features = (frappe.boot && frappe.boot.yht_features) || [];
				if (features.indexOf("oct11_r26_session_fiscal_year") === -1) return;
				if (frm.is_new() && frm.doc.custom_fiscal_year) {
					frm.doc.custom_fiscal_year = "";
					frm.refresh_field("custom_fiscal_year");
				}
				limit_new_document_dates(frm);
			},
			refresh(frm) {
				limit_new_document_dates(frm);
			},
		});
	});
})();
