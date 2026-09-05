// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Create New Supplier — the mirror of create_customer.js, ported from
// rmax_custom. Registered on Purchase Invoice, Purchase Order and Purchase
// Receipt.
//
//   B2C (Individual)  →  Supplier Name + Mobile only.
//   B2B (Company)     →  VAT (15 digits) + the full address as well.
//
// A supplier's VAT number lives in the core `tax_id`; there is no
// custom_vat_registration_number on Supplier here, because ZATCA's claims are
// about the buyer. Every rule below is re-checked in yht_custom.api.supplier.

frappe.provide("yht.create_supplier");

const YHT_S_B2B = "B2B (Company)";
const YHT_S_B2C = "B2C (Individual)";
const YHT_S_IS_B2B = `eval:doc.buyer_kind === '${YHT_S_B2B}'`;

["Purchase Invoice", "Purchase Order", "Purchase Receipt"].forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		refresh(frm) {
			yht.create_supplier.add_button(frm);
		},
	});
});

yht.create_supplier.add_button = function (frm) {
	if (frm.doc.docstatus !== 0) return;
	if (!frm.fields_dict.supplier) return;

	const $wrapper = frm.fields_dict.supplier.$wrapper;
	// refresh fires repeatedly; without this the buttons stack up down the form.
	if ($wrapper.parent().find(".yht-create-supplier-btn").length) return;

	const $btn = $(
		`<button type="button" class="btn btn-sm btn-secondary yht-create-supplier-btn" style="margin-bottom: 5px;">
			<i class="fa fa-plus"></i> ${__("Create New Supplier")}
		</button>`
	);
	$btn.on("click", () => open_dialog(frm));
	$wrapper.before($btn);
};

function open_dialog(frm) {
	frappe.call({
		method: "yht_custom.api.supplier.get_supplier_defaults",
		callback(r) {
			const defaults = r.message || {};
			if (!defaults.can_create) {
				frappe.msgprint({
					message: __("You do not have permission to create a Supplier."),
					indicator: "orange",
				});
				return;
			}
			render(frm, defaults);
		},
	});
}

function render(frm, defaults) {
	const can_override = !!defaults.can_override_vat;
	const b2b_only = { depends_on: YHT_S_IS_B2B, mandatory_depends_on: YHT_S_IS_B2B };

	const dialog = new frappe.ui.Dialog({
		title: __("Create New Supplier"),
		size: "large",
		fields: [
			{
				fieldname: "buyer_kind",
				fieldtype: "Select",
				label: __("Supplier Kind"),
				options: [YHT_S_B2C, YHT_S_B2B].join("\n"),
				default: YHT_S_B2C,
				reqd: 1,
				description: __("B2C: only Name + Mobile required. B2B: VAT + Address mandatory."),
			},

			{ fieldtype: "Section Break" },
			{ fieldname: "supplier_name", fieldtype: "Data", label: __("Supplier Name"), reqd: 1 },
			{
				fieldname: "supplier_group",
				fieldtype: "Link",
				label: __("Supplier Group"),
				options: "Supplier Group",
				filters: { is_group: 0 },
				default: defaults.supplier_group || "",
			},
			{ fieldtype: "Column Break" },
			{ fieldname: "mobile_no", fieldtype: "Data", label: __("Mobile No"), reqd: 1 },
			{ fieldname: "email_id", fieldtype: "Data", options: "Email", label: __("Email ID") },

			{ fieldtype: "Section Break", label: __("B2B Details"), depends_on: YHT_S_IS_B2B },
			Object.assign(
				{
					fieldname: "tax_id",
					fieldtype: "Data",
					label: __("VAT Registration Number"),
					description: __("Exactly {0} digits.", [defaults.vat_length || 15]),
				},
				b2b_only
			),
			{
				fieldname: "allow_duplicate_vat",
				fieldtype: "Check",
				label: __("Allow Duplicate VAT (Manager Override)"),
				default: 0,
				hidden: can_override ? 0 : 1,
				depends_on: `eval:doc.buyer_kind === '${YHT_S_B2B}' && doc.tax_id`,
			},
			{
				fieldname: "duplicate_vat_reason",
				fieldtype: "Small Text",
				label: __("Duplicate VAT Reason"),
				hidden: can_override ? 0 : 1,
				depends_on: "eval:doc.allow_duplicate_vat",
				mandatory_depends_on: "eval:doc.allow_duplicate_vat",
			},

			{ fieldtype: "Section Break", label: __("Address Details"), depends_on: YHT_S_IS_B2B },
			{
				fieldname: "address_type",
				fieldtype: "Select",
				label: __("Address Type"),
				options: "Billing\nShipping",
				default: "Billing",
				depends_on: YHT_S_IS_B2B,
			},
			Object.assign({ fieldname: "address_line1", fieldtype: "Data", label: __("Address Line 1") }, b2b_only),
			{ fieldname: "address_line2", fieldtype: "Data", label: __("Address Line 2"), depends_on: YHT_S_IS_B2B },
			Object.assign({ fieldname: "custom_building_number", fieldtype: "Data", label: __("Building Number") }, b2b_only),
			Object.assign({ fieldname: "custom_area", fieldtype: "Data", label: __("Area/District") }, b2b_only),
			{ fieldtype: "Column Break", depends_on: YHT_S_IS_B2B },
			Object.assign({ fieldname: "city", fieldtype: "Data", label: __("City/Town") }, b2b_only),
			Object.assign({ fieldname: "pincode", fieldtype: "Data", label: __("Postal Code") }, b2b_only),
			{
				fieldname: "custom_additional_number",
				fieldtype: "Data",
				label: __("Additional Number"),
				depends_on: YHT_S_IS_B2B,
			},
			{
				fieldname: "custom_short_address",
				fieldtype: "Data",
				label: __("Short Address"),
				depends_on: YHT_S_IS_B2B,
				description: __("e.g. RQAA2929"),
			},
			Object.assign(
				{ fieldname: "country", fieldtype: "Link", options: "Country", label: __("Country"), default: defaults.country },
				b2b_only
			),
		],

		primary_action_label: __("Create Supplier"),
		primary_action(values) {
			const is_b2b = values.buyer_kind === YHT_S_B2B;
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

			if (digits(values.tax_id).length !== vat_length) {
				frappe.msgprint(__("VAT must be exactly {0} digits.", [vat_length]));
				return;
			}
			if (digits(values.pincode).length !== 5) {
				frappe.msgprint(__("Postal Code must be exactly 5 digits."));
				return;
			}
			if (allow_dup) return submit();

			frappe.call({
				method: "yht_custom.api.supplier.check_vat_available",
				args: { vat: digits(values.tax_id) },
				callback(r) {
					const taken = (r.message || {}).taken_by;
					if (taken) {
						frappe.msgprint(
							__("VAT already exists for Supplier: {0}. A Sales Manager can tick 'Allow Duplicate VAT' to override.", [taken])
						);
						return;
					}
					submit();
				},
			});

			function submit() {
				dialog.disable_primary_action();
				frappe.call({
					method: "yht_custom.api.supplier.create_supplier_with_address",
					args: {
						supplier_name: values.supplier_name,
						buyer_kind: values.buyer_kind,
						supplier_group: values.supplier_group || null,
						mobile_no: values.mobile_no,
						email_id: values.email_id || null,
						tax_id: is_b2b ? values.tax_id : null,
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
						frm.set_value("supplier", r.message.supplier);
						frm.refresh_field("supplier");
						frappe.show_alert({ message: r.message.message, indicator: "green" });
						dialog.hide();
					},
					error() {
						dialog.enable_primary_action();
					},
				});
			}
		},
	});

	dialog.show();
	mask(dialog, "mobile_no", 15);
	mask(dialog, "tax_id", defaults.vat_length || 15);
	mask(dialog, "pincode", 5);
	mask(dialog, "custom_building_number", 4);
	mask(dialog, "custom_additional_number", 4);
}

function digits(value) {
	return (value || "").toString().replace(/\D/g, "");
}

function mask(dialog, fieldname, max) {
	const control = dialog.fields_dict[fieldname];
	if (!control || !control.$input) return;
	control.$input.on("input", function () {
		const value = digits(this.value).slice(0, max);
		if (this.value !== value) this.value = value;
	});
}
