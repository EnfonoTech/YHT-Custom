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

	try {
		if (sessionStorage.getItem("yht_session_year_shown")) return;
		sessionStorage.setItem("yht_session_year_shown", "1");
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
