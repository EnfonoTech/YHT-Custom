// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Row 46 (2026-10-16) — "show the connected documents as a table on the right side; click a number to
// open that document", like the old system's Delivery Note box.
//
// The numbers are stored Data fields (list columns, filters and reports read them; see
// `yht_custom/connected_documents.py`). They are hidden on the form and this renders them: one
// "Connected Documents" HTML field at the end of the front page's third column. Nothing here writes.
//
// Loaded through `doctype_js`, so it needs no `bench build`. It does nothing on a site where the HTML field
// does not exist (switch `oct15_r46_connected_numbers` off), so it is safe to ship everywhere.

(function () {
	const FIELD = "custom_connected_documents";

	// doctype -> [[label shown, stored field, doctype the number opens]]
	const MAP = {
		"Quotation": [["Sales Order", "custom_sales_order_no", "Sales Order"]],
		"Sales Order": [
			["Quotation", "custom_quotation_no", "Quotation"],
			["Delivery Note", "custom_delivery_note_no", "Delivery Note"],
			["Sales Invoice", "custom_sales_invoice_no", "Sales Invoice"],
		],
		"Sales Invoice": [
			["Sales Order", "custom_sales_order_no", "Sales Order"],
			["Delivery Note", "custom_delivery_note_no", "Delivery Note"],
		],
		"Purchase Order": [
			["Purchase Receipt", "custom_purchase_receipt_no", "Purchase Receipt"],
			["Purchase Invoice", "custom_purchase_invoice_no", "Purchase Invoice"],
		],
		"Purchase Receipt": [
			["Purchase Order", "custom_purchase_order_no", "Purchase Order"],
			["Purchase Invoice", "custom_purchase_invoice_no", "Purchase Invoice"],
		],
		"Purchase Invoice": [
			["Purchase Order", "custom_purchase_order_no", "Purchase Order"],
			["Purchase Receipt", "custom_purchase_receipt_no", "Purchase Receipt"],
		],
	};

	// The documents a Payment Entry is made against: their payments are read live (the server method
	// `linked_payments`), not stored, and shown under the same table.
	const PAYMENT_DOCS = ["Sales Invoice", "Sales Order", "Purchase Invoice", "Purchase Order"];

	function link(doctype, name) {
		const route = "/app/" + frappe.router.slug(doctype) + "/" + encodeURIComponent(name);
		return '<a href="' + route + '">' + frappe.utils.escape_html(name) + "</a>";
	}

	// Other Remarks is a note, three lines are plenty; its default box made the first column the tallest.
	function shorten_remarks(frm) {
		const remarks = frm.fields_dict.custom_other_remarks;
		if (remarks && remarks.$input) remarks.$input.css({ height: "64px", minHeight: "64px" });
	}

	function render(frm) {
		shorten_remarks(frm);
		const df = frm.fields_dict[FIELD];
		const spec = MAP[frm.doctype];
		if (!df || !spec || !df.$wrapper) return;

		const rows = [];
		spec.forEach(function (entry) {
			const label = entry[0], field = entry[1], target = entry[2];
			String(frm.doc[field] || "")
				.split(",")
				.map(function (part) { return part.trim(); })
				.filter(Boolean)
				.forEach(function (name) {
					// The stored value ends in an ellipsis when it was cut to fit; that name is not a link.
					const cut = name.indexOf("…") !== -1;
					rows.push(
						"<tr><td class='text-muted'>" + __(label) + "</td><td>" +
						(cut ? frappe.utils.escape_html(name) : link(target, name)) + "</td></tr>"
					);
				});
		});

		const payments = frm._yht_payments && frm._yht_payments.doc === frm.doc.name ? frm._yht_payments.rows : [];
		payments.forEach(function (p) {
			rows.push("<tr><td class='text-muted'>" + __("Payment Entry") + "</td><td>" + link("Payment Entry", p.name) + "</td></tr>");
		});

		const body = rows.length
			? rows.join("")
			: "<tr><td colspan='2' class='text-muted'>" + __("Nothing connected yet") + "</td></tr>";
		df.$wrapper.html(
			"<div class='yht-connected'><div class='control-label'>" + __("Connected Documents") + "</div>" +
			"<table class='table table-bordered' style='margin-bottom:0;border-radius:8px;border-collapse:separate;'>" +
			"<tbody>" + body + "</tbody></table></div>"
		);
	}

	function load_payments(frm) {
		if (!frm.fields_dict[FIELD] || PAYMENT_DOCS.indexOf(frm.doctype) === -1 || frm.is_new() || !frm.doc.name) return;
		const doc = frm.doc.name;
		frappe.call({
			method: "yht_custom.connected_documents.linked_payments",
			args: { doctype: frm.doctype, name: doc },
			callback: function (r) {
				if (frm.doc.name !== doc) return;
				frm._yht_payments = { doc: doc, rows: r.message || [] };
				render(frm);
			},
		});
	}

	function refresh(frm) {
		render(frm);
		load_payments(frm);
	}

	Object.keys(MAP).forEach(function (doctype) {
		frappe.ui.form.on(doctype, { refresh: refresh, onload_post_render: render });
	});
})();
