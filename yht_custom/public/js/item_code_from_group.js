// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Shows the item code that the selected Item Group will generate, so the user
// sees it before saving instead of being surprised by it afterwards.
//
// The preview does NOT consume the counter — the server fills the real code in
// before_insert. A preview that burned a number would leave a gap every time
// somebody opened a form and changed their mind.

frappe.ui.form.on("Item", {
	item_group(frm) {
		if (!frm.is_new()) return;
		show_code_preview(frm);
	},

	onload(frm) {
		if (frm.is_new() && frm.doc.item_group) show_code_preview(frm);
	},
});

function show_code_preview(frm) {
	if (!frm.doc.item_group) {
		frm.set_df_property("item_code", "description", "");
		return;
	}

	frappe.call({
		method: "yht_custom.item_naming.preview_item_code",
		args: { item_group: frm.doc.item_group },
		callback(r) {
			const res = r.message || {};
			if (!res.configured) {
				frm.set_df_property(
					"item_code",
					"description",
					__("This item group has no code prefix — enter the item code manually.")
				);
				frm.refresh_field("item_code");
				return;
			}

			frm.set_df_property(
				"item_code",
				"description",
				__("Leave blank to generate <b>{0}</b> automatically.", [frappe.utils.escape_html(res.next_code)])
			);
			frm.refresh_field("item_code");
		},
	});
}
