// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Branch Configuration", {
	refresh(frm) {
		// Constrain warehouse / cost center pickers to the selected company so a
		// mismatch is impossible to enter, rather than only caught on validate.
		frm.set_query("warehouse", "warehouse", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
		frm.set_query("cost_center", "cost_center", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
		// Only Cash and Bank modes make sense as a branch allowlist.
		frm.set_query("mode_of_payment", "mode_of_payment", () => ({
			filters: { type: ["in", ["Cash", "Bank"]] },
		}));

		if (!frm.is_new()) {
			frm.add_custom_button(__("Show Provisioned Permissions"), () => show_permissions(frm));
		}
	},

	company(frm) {
		// Company drives every child table filter — stale rows would fail validate.
		const stale = ["warehouse", "cost_center"].filter(
			(t) => (frm.doc[t] || []).some((r) => r.company && r.company !== frm.doc.company)
		);
		if (stale.length) {
			frappe.msgprint({
				title: __("Company Changed"),
				indicator: "orange",
				message: __("Rows in {0} belong to the previous company. Clear or re-pick them before saving.", [
					stale.join(", "),
				]),
			});
		}
	},
});

function show_permissions(frm) {
	const users = (frm.doc.user || []).map((r) => r.user).filter(Boolean);
	if (!users.length) {
		frappe.msgprint(__("No users on this Branch Configuration yet."));
		return;
	}
	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "User Permission",
			filters: { user: ["in", users] },
			fields: ["user", "allow", "for_value", "is_default"],
			limit_page_length: 0,
			order_by: "user asc, allow asc",
		},
		callback(r) {
			const rows = r.message || [];
			if (!rows.length) {
				frappe.msgprint(__("No User Permissions found. Save the document to provision them."));
				return;
			}
			const body = rows
				.map(
					(p) =>
						`<tr><td>${frappe.utils.escape_html(p.user)}</td>
						 <td>${frappe.utils.escape_html(p.allow)}</td>
						 <td>${frappe.utils.escape_html(p.for_value)}</td>
						 <td>${p.is_default ? __("Default") : ""}</td></tr>`
				)
				.join("");
			frappe.msgprint({
				title: __("Provisioned Permissions"),
				message: `<table class="table table-bordered table-sm">
					<thead><tr><th>${__("User")}</th><th>${__("Allow")}</th><th>${__("Value")}</th><th></th></tr></thead>
					<tbody>${body}</tbody></table>`,
				wide: true,
			});
		},
	});
}
