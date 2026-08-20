// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Stock Valuation Snapshot"] = {
	filters: [
		{ fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse" },
		{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{
			fieldname: "only_problems",
			label: __("Only Problems"),
			fieldtype: "Check",
			default: 0,
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		const red =
			(column.fieldname === "actual_qty" && flt(data.actual_qty) < 0) ||
			(column.fieldname === "qty_delta" && Math.abs(flt(data.qty_delta)) > 0.001) ||
			(column.fieldname === "value_delta" && Math.abs(flt(data.value_delta)) > 0.05) ||
			(column.fieldname === "valuation_rate" &&
				!flt(data.valuation_rate) &&
				flt(data.actual_qty) > 0);
		if (red) value = `<span style="color: var(--red-500)">${value}</span>`;
		return value;
	},
};
