// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Import Gate"] = {
	filters: [],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "status" && data) {
			const colour = { PASS: "--green-500", FAIL: "--red-500", ERROR: "--orange-500" }[data.status];
			if (colour) value = `<span style="color: var(${colour}); font-weight: 600">${value}</span>`;
		}
		return value;
	},
};
