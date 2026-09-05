// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Create New Customer — ported from rmax_custom so the fleet behaves alike.
//
//   B2C (Individual)  →  Customer Name + Mobile only.
//   B2B (Company)     →  VAT (15 digits) + the full national address as well,
//                        because that is what a standard e-invoice needs to clear.
//
// Sales Manager / Sales Master Manager / System Manager may tick Allow Duplicate
// VAT, and must say why. Every one of these rules is re-checked in
// yht_custom.api.customer — the dialog exists to fail fast, not to be the
// boundary.
//
// opts.customerField — the field to fill once the customer exists:
//   "customer" on Sales Invoice, "party_name" on Quotation.

frappe.provide("yht.create_customer");

const YHT_B2B = "B2B (Company)";
const YHT_B2C = "B2C (Individual)";
const YHT_IS_B2B = `eval:doc.buyer_kind === '${YHT_B2B}'`;

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		yht.create_customer.add_button(frm, { customerField: "customer" });
	},
});

frappe.ui.form.on("Quotation", {
	refresh(frm) {
		// party_name only points at a Customer when quotation_to says so.
		if (frm.doc.quotation_to && frm.doc.quotation_to !== "Customer") return;
		yht.create_customer.add_button(frm, {
			customerField: "party_name",
			preAction() {
				if (frm.doc.quotation_to !== "Customer") frm.set_value("quotation_to", "Customer");
			},
		});
	},
});

yht.create_customer.add_button = function (frm, opts) {
	opts = opts || {};
	const field = opts.customerField || "customer";

	if (frm.doc.docstatus !== 0) return;
	if (!frm.fields_dict[field]) return;

	const $wrapper = frm.fields_dict[field].$wrapper;
	// refresh fires repeatedly; without this the buttons stack up down the form.
	if ($wrapper.parent().find(".yht-create-customer-btn").length) return;

	const $btn = $(
		`<button type="button" class="btn btn-sm btn-secondary yht-create-customer-btn" style="margin-bottom: 5px;">
			<i class="fa fa-plus"></i> ${__("Create New Customer")}
		</button>`
	);
	$btn.on("click", () => {
		if (opts.preAction) opts.preAction();
		open_dialog(frm, field);
	});
	$wrapper.before($btn);
};

function open_dialog(frm, customerField) {
	frappe.call({
		method: "yht_custom.api.customer.get_customer_defaults",
		callback(r) {
			const defaults = r.message || {};
			if (!defaults.can_create) {
				frappe.msgprint({
					message: __("You do not have permission to create a Customer."),
					indicator: "orange",
				});
				return;
			}
			render(frm, customerField, defaults);
		},
	});
}

function render(frm, customerField, defaults) {
	const can_override = !!defaults.can_override_vat;

	const dialog = new frappe.ui.Dialog({
		title: __("Create New Customer"),
		size: "large",
		fields: [
			{
				fieldname: "buyer_kind",
				fieldtype: "Select",
				label: __("Customer Kind"),
				options: [YHT_B2C, YHT_B2B].join("\n"),
				default: YHT_B2C,
				reqd: 1,
				description: __("B2C: only Name + Mobile required. B2B: VAT + Address mandatory."),
			},

			{ fieldtype: "Section Break" },
			{ fieldname: "customer_name", fieldtype: "Data", label: __("Customer Name"), reqd: 1 },
			{
				fieldname: "custom_customer_name_arabic",
				fieldtype: "Data",
				label: __("Customer Name (Arabic)"),
				description: __("Optional. Prints on the bilingual ZATCA format."),
			},
			{
				fieldname: "customer_group",
				fieldtype: "Link",
				label: __("Customer Group"),
				options: "Customer Group",
				filters: { is_group: 0 },
				default: defaults.customer_group || "",
			},
			{ fieldtype: "Column Break" },
			{ fieldname: "mobile_no", fieldtype: "Data", label: __("Mobile No"), reqd: 1 },
			{ fieldname: "email_id", fieldtype: "Data", options: "Email", label: __("Email ID") },

			{ fieldtype: "Section Break", label: __("B2B Details"), depends_on: YHT_IS_B2B },
			{
				fieldname: "custom_vat_registration_number",
				fieldtype: "Data",
				label: __("VAT Registration Number"),
				depends_on: YHT_IS_B2B,
				mandatory_depends_on: YHT_IS_B2B,
				description: __("Exactly {0} digits.", [defaults.vat_length || 15]),
			},
			{
				fieldname: "allow_duplicate_vat",
				fieldtype: "Check",
				label: __("Allow Duplicate VAT (Manager Override)"),
				default: 0,
				hidden: can_override ? 0 : 1,
				depends_on: `eval:doc.buyer_kind === '${YHT_B2B}' && doc.custom_vat_registration_number`,
			},
			{
				fieldname: "duplicate_vat_reason",
				fieldtype: "Small Text",
				label: __("Duplicate VAT Reason"),
				hidden: can_override ? 0 : 1,
				depends_on: "eval:doc.allow_duplicate_vat",
				mandatory_depends_on: "eval:doc.allow_duplicate_vat",
			},

			{ fieldtype: "Section Break", label: __("Address Details"), depends_on: YHT_IS_B2B },
			{
				fieldname: "address_type",
				fieldtype: "Select",
				label: __("Address Type"),
				options: "Billing\nShipping",
				default: "Billing",
				depends_on: YHT_IS_B2B,
			},
			{
				fieldname: "address_line1",
				fieldtype: "Data",
				label: __("Address Line 1"),
				depends_on: YHT_IS_B2B,
				mandatory_depends_on: YHT_IS_B2B,
			},
			{ fieldname: "address_line2", fieldtype: "Data", label: __("Address Line 2"), depends_on: YHT_IS_B2B },
			{
				fieldname: "custom_building_number",
				fieldtype: "Data",
				label: __("Building Number"),
				depends_on: YHT_IS_B2B,
				mandatory_depends_on: YHT_IS_B2B,
			},
			{
				fieldname: "custom_area",
				fieldtype: "Data",
				label: __("Area/District"),
				depends_on: YHT_IS_B2B,
				mandatory_depends_on: YHT_IS_B2B,
			},
			{ fieldtype: "Column Break", depends_on: YHT_IS_B2B },
			{
				fieldname: "city",
				fieldtype: "Data",
				label: __("City/Town"),
				depends_on: YHT_IS_B2B,
				mandatory_depends_on: YHT_IS_B2B,
			},
			{
				fieldname: "pincode",
				fieldtype: "Data",
				label: __("Postal Code"),
				depends_on: YHT_IS_B2B,
				mandatory_depends_on: YHT_IS_B2B,
			},
			// Not in the rmax dialog, but this site's Address validator knows them and
			// the national address is the whole reason the block is here.
			{
				fieldname: "custom_additional_number",
				fieldtype: "Data",
				label: __("Additional Number"),
				depends_on: YHT_IS_B2B,
			},
			{
				fieldname: "custom_short_address",
				fieldtype: "Data",
				label: __("Short Address"),
				depends_on: YHT_IS_B2B,
				description: __("e.g. RQAA2929"),
			},
			{
				fieldname: "country",
				fieldtype: "Link",
				options: "Country",
				label: __("Country"),
				default: defaults.country,
				depends_on: YHT_IS_B2B,
				mandatory_depends_on: YHT_IS_B2B,
			},
		],

		primary_action_label: __("Create Customer"),
		primary_action(values) {
			const is_b2b = values.buyer_kind === YHT_B2B;
			const vat_length = defaults.vat_length || 15;

			if (digits(values.mobile_no).length < 10) {
				frappe.msgprint(__("Mobile number must have at least 10 digits."));
				return;
			}

			const allow_dup = values.allow_duplicate_vat ? 1 : 0;
			const reason = (values.duplicate_vat_reason || "").trim();
			if (allow_dup && !can_override) {
				frappe.msgprint(
					__("You do not have permission to override the VAT duplicate check. Required role: Sales Manager.")
				);
				return;
			}
			if (allow_dup && !reason) {
				frappe.msgprint(__("Please provide the Duplicate VAT Reason."));
				return;
			}

			if (!is_b2b) return submit();

			const vat = digits(values.custom_vat_registration_number);
			if (vat.length !== vat_length) {
				frappe.msgprint(__("VAT must be exactly {0} digits.", [vat_length]));
				return;
			}
			if (digits(values.pincode).length !== 5) {
				frappe.msgprint(__("Postal Code must be exactly 5 digits."));
				return;
			}
			if (allow_dup) return submit();

			// Ask before the operator has typed an address for nothing. The server
			// checks again — this is courtesy, not enforcement.
			frappe.call({
				method: "yht_custom.api.customer.check_vat_available",
				args: { vat },
				callback(r) {
					const taken = (r.message || {}).taken_by;
					if (taken) {
						frappe.msgprint(
							__("VAT already exists for Customer: {0}. A Sales Manager can tick 'Allow Duplicate VAT' to override.", [taken])
						);
						return;
					}
					submit();
				},
			});

			function submit() {
				dialog.disable_primary_action();
				frappe.call({
					method: "yht_custom.api.customer.create_customer_with_address",
					args: {
						customer_name: values.customer_name,
						buyer_kind: values.buyer_kind,
						customer_group: values.customer_group || null,
						mobile_no: values.mobile_no,
						email_id: values.email_id || null,
						custom_customer_name_arabic: values.custom_customer_name_arabic || null,
						custom_vat_registration_number: is_b2b ? values.custom_vat_registration_number : null,
						allow_duplicate_vat: allow_dup,
						duplicate_vat_reason: allow_dup ? reason : null,
						address_type: is_b2b ? values.address_type : null,
						address_line1: is_b2b ? values.address_line1 : null,
						address_line2: is_b2b ? values.address_line2 || null : null,
						custom_building_number: is_b2b ? values.custom_building_number : null,
						custom_area: is_b2b ? values.custom_area : null,
						custom_additional_number: is_b2b ? values.custom_additional_number || null : null,
						custom_short_address: is_b2b ? values.custom_short_address || null : null,
						city: is_b2b ? values.city : null,
						pincode: is_b2b ? values.pincode : null,
						country: is_b2b ? values.country : null,
					},
					callback(r) {
						if (!r.message) {
							dialog.enable_primary_action();
							return;
						}
						frm.set_value(customerField, r.message.customer);
						frm.refresh_field(customerField);
						frappe.show_alert({ message: r.message.message, indicator: "green" });
						dialog.hide();
					},
					// A server-side throw must leave the typing on screen.
					error() {
						dialog.enable_primary_action();
					},
				});
			}
		},
	});

	dialog.show();
	mask(dialog, "mobile_no", 15);
	mask(dialog, "custom_vat_registration_number", defaults.vat_length || 15);
	mask(dialog, "pincode", 5);
	mask(dialog, "custom_building_number", 4);
	mask(dialog, "custom_additional_number", 4);
}

function digits(value) {
	return (value || "").toString().replace(/\D/g, "");
}

// Digits only, capped — the server rejects anything else, and finding that out
// after typing an address is a poor way to learn it.
function mask(dialog, fieldname, max) {
	const control = dialog.fields_dict[fieldname];
	if (!control || !control.$input) return;
	control.$input.on("input", function () {
		const value = digits(this.value).slice(0, max);
		if (this.value !== value) this.value = value;
	});
}
