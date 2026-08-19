// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Expense Purchase Invoice, form side.
//
// Strips a Purchase Invoice down to what an expense actually needs, so the person
// entering the electricity bill is not looking at warehouses and receipts.

frappe.ui.form.on("Purchase Invoice", {
	onload(frm) {
		shape(frm);
	},
	refresh(frm) {
		shape(frm);
	},
	custom_is_expense_invoice(frm) {
		shape(frm);
		if (frm.doc.custom_is_expense_invoice) {
			frm.set_value("update_stock", 0);
		}
	},
	custom_expense_head(frm) {
		// Stamp the head onto rows that have no account yet. The server does this
		// too; doing it here means the user sees it before saving.
		const head = frm.doc.custom_expense_head;
		if (!head) return;
		(frm.doc.items || []).forEach((row) => {
			if (!row.expense_account) {
				frappe.model.set_value(row.doctype, row.name, "expense_account", head);
			}
		});
	},
});

// Stock-item rows are rejected server-side, so keep them out of the picker.
frappe.ui.form.on("Purchase Invoice Item", {
	items_add(frm, cdt, cdn) {
		if (!frm.doc.custom_is_expense_invoice) return;
		const head = frm.doc.custom_expense_head;
		if (head) frappe.model.set_value(cdt, cdn, "expense_account", head);
		frappe.model.set_value(cdt, cdn, "qty", 1);
		// `uom` is mandatory on Purchase Invoice Item, and an expense line has no natural
		// unit. Set it here so the operator is not stopped by "UOM is required in every row"
		// on a line that reads "printing". before_validate does the same server-side, which is
		// what covers the REST and import paths.
		if (!frappe.get_doc(cdt, cdn).uom) {
			frappe.model.set_value(cdt, cdn, "uom", frappe.boot.sysdefaults.stock_uom || "Nos");
		}
	},
});

const STOCK_FIELDS = [
	"update_stock",
	"set_warehouse",
	"set_from_warehouse",
	"rejected_warehouse",
	"supplier_warehouse",
	"is_subcontracted",
];

function shape(frm) {
	const is_expense = !!frm.doc.custom_is_expense_invoice;

	STOCK_FIELDS.forEach((f) => {
		if (frm.fields_dict[f]) frm.set_df_property(f, "hidden", is_expense ? 1 : 0);
	});

	// Drop frappe's blank starter row, and give every remaining row a uom.
	//
	// frappe puts one empty row on a new child table, and `shape()` stamps the expense head
	// onto it — which makes it non-empty, so nothing drops it, and the CLIENT then refuses the
	// save before the request is ever sent. Filling `uom` was not enough: `item_name` is
	// mandatory too, so the refusal just moved to
	//     "In Items, Item Name is required in row 1."
	// An expense invoice starts with no lines, so the honest fix is to remove the blank row
	// rather than invent values for it.
	//
	// Guarded on `__islocal` and on the row being ENTIRELY blank, so a saved document is never
	// touched and a row someone is midway through typing is never pulled out from under them.
	if (is_expense && frm.doc.__islocal && frm.fields_dict.items) {
		const grid = frm.fields_dict.items.grid;
		const blank = (frm.doc.items || []).filter(
			(row) => !row.item_code && !row.item_name && !row.description && !flt(row.rate) && !flt(row.amount)
		);
		if (blank.length && blank.length < (frm.doc.items || []).length + 1) {
			blank.forEach((row) => grid.grid_rows_by_docname[row.name]?.remove());
			frm.refresh_field("items");
		}
	}

	if (is_expense) {
		const fallback = frappe.boot.sysdefaults.stock_uom || "Nos";
		(frm.doc.items || []).forEach((row) => {
			if (!row.uom) frappe.model.set_value(row.doctype, row.name, "uom", fallback);
		});
	}

	if (frm.fields_dict.items) {
		// An expense line is a description and an account, not an item and a store.
		["warehouse", "from_warehouse", "rejected_warehouse", "received_qty", "rejected_qty"].forEach((f) => {
			if (frm.get_docfield("items", f)) {
				frm.fields_dict.items.grid.update_docfield_property(f, "hidden", is_expense ? 1 : 0);
			}
		});
		// `update_docfield_property(fieldname, property, value)` — in that order.
		//
		// This line used to read `update_docfield_property("in_list_view", 1)`, passing the
		// PROPERTY as the fieldname and never using the loop variable at all. frappe's
		// implementation THROWS on a fieldname it cannot resolve (`throw \`field ${fieldname}
		// not found\``), so ticking Is Expense Invoice raised an exception every single time,
		// the grid was never reshaped, and the form could not be completed. Found while
		// capturing the expense-invoice training video: the save failed with a bare
		// "Missing Fields" modal that named nothing.
		["item_name", "expense_account", "rate", "amount"].forEach((f) => {
			if (frm.get_docfield("items", f)) {
				frm.fields_dict.items.grid.update_docfield_property(f, "in_list_view", 1);
			}
		});
	}

	if (is_expense) {
		frm.set_query("expense_account", "items", () => ({
			filters: { root_type: "Expense", is_group: 0, company: frm.doc.company },
		}));
		if (!frm.doc.__islocal) return;
		frm.set_df_property(
			"custom_expense_head",
			"description",
			__("Pick the expense once here — every line inherits it.")
		);
	}
}
