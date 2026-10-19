// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Inter Branch Sale", {
	setup(frm) {
		frm.set_query("customer", function () {
			return { filters: { name: ["in", frm._ib_customers || []] } };
		});
		frm.set_query("warehouse", "items", function () {
			return { filters: { company: frm.doc.company, is_group: 0 } };
		});
	},
	refresh(frm) {
		frappe.call({
			method: "yht_custom.yht_custom.doctype.inter_branch_sale.inter_branch_sale.get_inter_branch_customers",
			callback(r) { frm._ib_customers = r.message || []; },
		});
	},
	from_warehouse(frm) {
		(frm.doc.items || []).forEach(function (row) {
			if (!row.warehouse) frappe.model.set_value(row.doctype, row.name, "warehouse", frm.doc.from_warehouse);
		});
	},
});

frappe.ui.form.on("Inter Branch Sale Item", {
	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_code) return;
		const warehouse = row.warehouse || frm.doc.from_warehouse;
		frappe.model.set_value(cdt, cdn, "warehouse", warehouse);
		frappe.call({
			method: "yht_custom.yht_custom.doctype.inter_branch_sale.inter_branch_sale.get_item_rates",
			args: { item_code: row.item_code, warehouse: warehouse, price_list: frm.doc.price_list },
			callback(r) {
				const rates = r.message || {};
				frappe.model.set_value(cdt, cdn, "valuation_rate", rates.valuation_rate || 0);
				if (!row.rate && rates.price_list_rate) frappe.model.set_value(cdt, cdn, "rate", rates.price_list_rate);
			},
		});
	},
	qty: function (frm, cdt, cdn) { recalc(frm, cdt, cdn); },
	rate: function (frm, cdt, cdn) { recalc(frm, cdt, cdn); },
	items_remove(frm) { totals(frm); },
});

function recalc(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "amount", flt(row.qty) * flt(row.rate));
	frappe.model.set_value(cdt, cdn, "cost_amount", flt(row.qty) * flt(row.valuation_rate));
	totals(frm);
}

function totals(frm) {
	let qty = 0, amount = 0, cost = 0;
	(frm.doc.items || []).forEach(function (r) {
		qty += flt(r.qty);
		amount += flt(r.qty) * flt(r.rate);
		cost += flt(r.qty) * flt(r.valuation_rate);
	});
	frm.set_value({ total_qty: qty, total_amount: amount, total_cost: cost, margin: amount - cost });
}
