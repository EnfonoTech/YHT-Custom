// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Simple Customer / Supplier creation (plan 5.10).
//
// One dialog, one server call. The address is part of the SAME form rather than a
// second screen, because on this site every Saudi address is missing its district
// and every Standard e-invoice needs one — an address step an operator can skip is
// an address step that gets skipped.
//
// Nothing here is a permission boundary. `yht_custom.api.party.create_party`
// checks `has_permission(doctype, "create")` itself; this file only decides
// whether to bother drawing the button.

frappe.provide("yht.simple_party");

const SAUDI_HINT = __("4 digits");

function address_fields() {
	return [
		{ fieldtype: "Section Break", label: __("National Address") },
		{ fieldname: "address_line1", fieldtype: "Data", label: __("Street Name") },
		{ fieldname: "custom_building_number", fieldtype: "Data", label: __("Building Number"), description: SAUDI_HINT },
		{ fieldname: "custom_area", fieldtype: "Data", label: __("District") },
		{ fieldtype: "Column Break" },
		{ fieldname: "city", fieldtype: "Data", label: __("City") },
		{ fieldname: "pincode", fieldtype: "Data", label: __("Postal Code"), description: __("5 digits") },
		{ fieldname: "custom_additional_number", fieldtype: "Data", label: __("Additional Number"), description: SAUDI_HINT },
		{ fieldname: "custom_short_address", fieldtype: "Data", label: __("Short Address"), description: __("e.g. RQAA2929") },
	];
}

function party_fields(doctype, defaults) {
	const is_customer = doctype === "Customer";
	const fields = [
		{
			fieldname: "party_name",
			fieldtype: "Data",
			label: is_customer ? __("Customer Name") : __("Supplier Name"),
			reqd: 1,
		},
		{ fieldname: "tax_id", fieldtype: "Data", label: __("VAT Number") },
		{ fieldtype: "Column Break" },
		{
			fieldname: "group",
			fieldtype: "Link",
			options: is_customer ? "Customer Group" : "Supplier Group",
			label: __("Group"),
			default: defaults.group,
		},
	];

	if (is_customer) {
		fields.push({
			fieldname: "territory",
			fieldtype: "Link",
			options: "Territory",
			label: __("Territory"),
			default: defaults.territory,
		});
	}

	return fields.concat(
		[
			{ fieldtype: "Section Break", label: __("Contact") },
			{ fieldname: "mobile", fieldtype: "Data", label: __("Mobile") },
			{ fieldtype: "Column Break" },
			{ fieldname: "email", fieldtype: "Data", options: "Email", label: __("Email") },
		],
		address_fields()
	);
}

yht.simple_party.open = function (doctype, on_created) {
	frappe.call({
		method: "yht_custom.api.party.get_party_defaults",
		args: { doctype },
		callback(r) {
			const defaults = r.message || {};
			if (!defaults.can_create) {
				frappe.msgprint({
					message: __("You do not have permission to create a {0}.", [__(doctype)]),
					indicator: "orange",
				});
				return;
			}
			show_dialog(doctype, defaults, on_created);
		},
	});
};

function show_dialog(doctype, defaults, on_created) {
	const dialog = new frappe.ui.Dialog({
		title: doctype === "Customer" ? __("New Customer") : __("New Supplier"),
		size: "large",
		fields: party_fields(doctype, defaults),
		primary_action_label: __("Create"),
		primary_action(values) {
			const address = {};
			[
				"address_line1",
				"custom_building_number",
				"custom_area",
				"custom_additional_number",
				"custom_short_address",
				"city",
				"pincode",
			].forEach((field) => {
				if (values[field]) address[field] = values[field];
			});
			address.country = defaults.country;

			dialog.disable_primary_action();
			frappe.call({
				method: "yht_custom.api.party.create_party",
				args: {
					doctype,
					party_name: values.party_name,
					tax_id: values.tax_id,
					group: values.group,
					territory: values.territory,
					mobile: values.mobile,
					email: values.email,
					address,
				},
				callback(r) {
					if (!r.message) {
						dialog.enable_primary_action();
						return;
					}
					dialog.hide();
					frappe.show_alert(
						{ message: __("{0} created", [r.message.name]), indicator: "green" },
						5
					);
					if (on_created) on_created(r.message);
					else frappe.set_route("Form", doctype, r.message.name);
				},
				// A server-side throw (a malformed postal code, say) must leave the
				// dialog open with the values still in it, not swallow the typing.
				error() {
					dialog.enable_primary_action();
				},
			});
		},
	});
	dialog.show();
}

// ── list-view button ─────────────────────────────────────────────────────────
["Customer", "Supplier"].forEach((doctype) => {
	frappe.listview_settings = frappe.listview_settings || {};
	const existing = frappe.listview_settings[doctype] || {};
	const previous = existing.onload;
	frappe.listview_settings[doctype] = Object.assign(existing, {
		onload(listview) {
			if (previous) previous.call(this, listview);
			listview.page.add_inner_button(__("Quick Create"), () => yht.simple_party.open(doctype));
		},
	});
});
