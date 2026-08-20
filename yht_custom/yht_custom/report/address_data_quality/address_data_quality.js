// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Address Data Quality"] = {
	filters: [
		{
			fieldname: "party_type",
			label: __("Party Type"),
			fieldtype: "Select",
			options: ["", "Customer", "Supplier"],
		},
		{
			fieldname: "only_problems",
			label: __("Only Addresses With Problems"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "blocks_zatca",
			label: __("Only ZATCA Blockers"),
			fieldtype: "Check",
			default: 0,
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "missing" && data.missing) {
			value = `<span style="color: var(--red-500)">${value}</span>`;
		}
		if (column.fieldname === "malformed" && data.malformed) {
			value = `<span style="color: var(--orange-500)">${value}</span>`;
		}
		return value;
	},
};
