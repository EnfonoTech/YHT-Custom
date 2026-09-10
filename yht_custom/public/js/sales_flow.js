// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Delivery-Note-compulsory flow, form side.
//
// The lock here is convenience. yht_custom.sales_flow enforces the same rule on
// before_validate, so a REST call or an import cannot route around it.

frappe.provide("yht_custom.flow");

yht_custom.flow.may_direct = null;

yht_custom.flow.check = function () {
	if (yht_custom.flow.may_direct !== null) return Promise.resolve(yht_custom.flow.may_direct);
	return frappe.call({ method: "yht_custom.sales_flow.may_use_direct_stock" }).then((r) => {
		yht_custom.flow.may_direct = !!r.message;
		return yht_custom.flow.may_direct;
	});
};

// ------------------------------------------------- Update Stock, form side
//
// Client sheet item 25. This REPLACED a role-driven handler that un-ticked
// `update_stock` on every new invoice and greyed the box out for anyone without
// a bypass role. The rule is now a LINKAGE test, not a role test: a standalone
// invoice opens ticked for everybody, and the box is only taken away when the
// goods have already moved. `yht_custom.sales_flow.enforce_delivery_note_route`
// and its purchase twin decide the same thing on before_validate, so a REST
// call cannot route around this — the form's job is to say WHY, before a save.
//
// ⚠️ READ-ONLY, NEVER HIDDEN. The operator has to SEE that the box is off and
// read the reason; a field that has vanished just looks like a missing feature.
// (erpnext's own `depends_on` does hide it once a row carries the link — that
// is upstream's call, and in that state there is nothing to reconcile anyway.)
//
// `frm.set_df_property` on a HEADER field is safe. The recorded no-op is about
// GRID cells, which need the six-argument per-row form.
const STOCK_ROUTE = {
	"Sales Invoice": {
		row_link: "dn_detail",
		order_link: "so_detail",
		moved: __("These goods have already gone out on a Delivery Note."),
		ordered: __("The Sales Order behind this invoice has already been delivered."),
	},
	"Purchase Invoice": {
		row_link: "pr_detail",
		order_link: "po_detail",
		moved: __("These goods have already arrived on a Purchase Receipt."),
		ordered: __("The Purchase Order behind this bill has already been received."),
	},
};

function lock_update_stock(frm, reason) {
	frm.set_df_property("update_stock", "read_only", reason ? 1 : 0);
	frm.set_df_property("update_stock", "description", reason || "");
}

function apply_stock_route(frm) {
	const spec = STOCK_ROUTE[frm.doc.doctype];
	if (!spec) return;

	const rows = frm.doc.items || [];

	// 🔴 CLEAR THE CACHE KEY ON EVERY PATH THAT DOES NOT SET IT. It is only ever
	// written on the server-probe path below, so without this a form that HAD
	// order-linked rows keeps the old signature after those rows are removed —
	// and the next call matching that stale signature returns early at the
	// `=== signature` check, leaving the "already gone out" read-only and its
	// description on screen for a document that no longer has anything behind it.
	if (rows.some((row) => row[spec.row_link])) {
		frm.__yht_stock_route = null;
		lock_update_stock(frm, spec.moved);
		return;
	}

	const details = rows.map((row) => row[spec.order_link]).filter(Boolean);
	if (!details.length) {
		frm.__yht_stock_route = null;
		lock_update_stock(frm, null);
		return;
	}

	// Only the server can answer "has the order behind this line already
	// shipped". Cached per set of rows so a refresh storm does not become a
	// request storm.
	const signature = details.slice().sort().join("|");
	if (frm.__yht_stock_route === signature) return;
	frm.__yht_stock_route = signature;

	frappe
		.call({
			method: "yht_custom.sales_flow.sales_order_has_stock_document",
			args: { doctype: frm.doc.doctype, details: JSON.stringify(details) },
		})
		.then((r) => {
			if (frm.__yht_stock_route !== signature) return;
			lock_update_stock(frm, r && r.message ? spec.ordered : null);
		});
}

for (const doctype of Object.keys(STOCK_ROUTE)) {
	frappe.ui.form.on(doctype, {
		// Both events, and both are needed: `refresh` alone misses the first
		// paint of a mapped document, `onload` alone misses a re-render after the
		// items grid changes.
		onload(frm) {
			apply_stock_route(frm);
		},
		refresh(frm) {
			apply_stock_route(frm);
		},
	});
}

frappe.ui.form.on("Delivery Note", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		yht_custom.flow.check().then((may_direct) => {
			if (may_direct) return;
			// Submitted DNs are locked server-side; say so rather than letting the
			// user discover it by having a save rejected.
			frm.dashboard.add_comment(
				__("This Delivery Note is submitted and locked. Raise a return to correct it."),
				"orange",
				true
			);
		});
	},
});


// ------------------------------------------------------- new sales return
//
// 🔴 A SHORTCUT CANNOT TICK `is_return`, AND NEITHER CAN A URL.
//
// `Sales Invoice.is_return` is `no_copy = 1`, and `create_new.js` skips every no_copy
// field when it applies `frappe.route_options`:
//
//     if (df && !df.no_copy) doc[fieldname] = value;
//
// Measured on the site, all three obvious routes come back with is_return = 0:
//   · /app/sales-invoice/new?is_return=1   — frappe also STRIPS the query string, so a
//     client script cannot recover it either
//   · the same with a #hash                — stripped as well
//   · frappe.new_doc("Sales Invoice", { is_return: 1 })
//
// Only setting it AFTER the form exists works. Hence this helper: everything that
// offers a "Sales Return" entry point routes through it.
//
// Ticking it is what earns the separate entry point — `branch_defaults` picks the
// naming series from `is_return` at before_insert, so a BRANCH USER's document numbers
// KSSR- (credit note) instead of KSIN-, which is the whole reason an accountant wants
// the two apart. A user holding a bypass role (System Manager, Accounts Manager, Sales
// Manager, …) is exempt from that override by design and keeps whatever the picker
// shows, so the alert below does not promise a series.

frappe.provide("yht_custom.sales");

// `frappe.new_doc` resolves before the form has finished rendering, and how long that
// takes depends on where the click came from: from a list view the form is ready almost
// at once, from a Page (the branch dashboard) it is not. A single readiness check passed
// on the list and bailed out silently on the dashboard, leaving an ORDINARY invoice open
// — the operator's next click was a sale, not a credit note. Wait for the form instead.
function wait_for_new_form(doctype, tries = 40) {
	return new Promise((resolve) => {
		const tick = () => {
			const frm = window.cur_frm;
			if (frm && frm.doc && frm.doc.doctype === doctype && frm.doc.__islocal) {
				return resolve(frm);
			}
			if (--tries <= 0) return resolve(null);
			setTimeout(tick, 100);
		};
		tick();
	});
}

// ⚠️ ONLY Sales Invoice and Purchase Invoice can start life as a return. `is_return`
// is READ-ONLY on Delivery Note and Purchase Receipt (measured on the meta), so a blank
// return of those cannot be created at all — theirs must be raised from the document
// being reversed, which is also what the return policy requires.
yht_custom.sales.RETURNABLE = ["Sales Invoice", "Purchase Invoice"];

// 🔴 A DELIVERY NOTE / PURCHASE RECEIPT RETURN CANNOT START AS A BLANK DOCUMENT.
// `is_return` is read_only = 1 AND no_copy = 1 on both, so nothing — not a route option,
// not a filtered list's "+ Add", not frappe.new_doc — can pre-tick it. Using the list's
// own Add button gives you an ordinary KSDN- note, silently, which is exactly what a
// branch user hit. The supported route is the mapper, which needs the source document,
// so ask for it.
//
// erpnext.stock.doctype.delivery_note.delivery_note.make_sales_return(source_name)
// erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_return(source_name)
yht_custom.sales.STOCK_RETURN = {
	"Delivery Note": {
		method: "erpnext.stock.doctype.delivery_note.delivery_note.make_sales_return",
		title: __("Which delivery note are the goods coming back from?"),
		label: __("Delivery Note"),
	},
	"Purchase Receipt": {
		method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_return",
		title: __("Which receipt are the goods going back on?"),
		label: __("Purchase Receipt"),
	},
};

yht_custom.sales.new_stock_return = function (doctype) {
	const spec = yht_custom.sales.STOCK_RETURN[doctype];
	if (!spec) return;

	const d = new frappe.ui.Dialog({
		title: spec.title,
		fields: [
			{
				fieldname: "source",
				fieldtype: "Link",
				options: doctype,
				label: spec.label,
				reqd: 1,
				// Submitted, not itself a return, and not already fully returned — the
				// last one is what stops a second return against the same goods.
				get_query: () => ({
					filters: { docstatus: 1, is_return: 0, per_returned: ["<", 100] },
				}),
			},
		],
		primary_action_label: __("Create Return"),
		async primary_action(values) {
			d.hide();
			// open_mapped_doc calls the whitelisted mapper and routes to the result, so
			// the return arrives with is_return, return_against and the negative
			// quantities already set by erpnext itself.
			frappe.model.open_mapped_doc({ method: spec.method, source_name: values.source });

			// The picker still shows the FORWARD series until the document is saved —
			// the branch series is chosen server-side at before_insert, and it does
			// pick the right one (verified: KSDR-26-0025). But an operator seeing
			// KSDN- and getting KSDR- reads that as a bug, so show the answer now.
			const frm = await wait_for_new_form(doctype);
			if (!frm) return;
			try {
				const r = await frappe.call({
					method: "yht_custom.sales_flow.return_naming_series",
					args: { doctype: doctype },
				});
				const series = r && r.message;
				if (!series) return;
				const df = frm.get_field("naming_series");
				const options = (df && df.df.options ? df.df.options.split("\n") : []).map((o) => o.trim());
				if (options.includes(series)) await frm.set_value("naming_series", series);
			} catch (e) {
				// A bypass role or an unconfigured branch is not an error.
			}
		},
	});
	d.show();
};

yht_custom.sales.new_return = async function (doctype) {
	doctype = doctype || "Sales Invoice";
	if (!yht_custom.sales.RETURNABLE.includes(doctype)) {
		frappe.msgprint({
			title: __("Start From the Original"),
			indicator: "orange",
			message: __("A {0} return has to be raised from the document it reverses — open it and use <b>Create &gt; Return</b>.", [__(doctype)]),
		});
		return;
	}
	await frappe.new_doc(doctype);
	const frm = await wait_for_new_form(doctype);
	if (!frm) {
		frappe.show_alert({ message: __("Could not open a return — try again"), indicator: "red" });
		return;
	}
	await frm.set_value("is_return", 1);

	// The picker still shows the form's pre-filled invoice series: the real choice happens
	// server-side at before_insert. Ask for the answer and show it, or the operator sees
	// KSIN- on screen, saves, and gets KSSR- — which reads as a bug rather than a feature.
	let series = null;
	try {
		const r = await frappe.call({
			method: "yht_custom.sales_flow.return_naming_series",
			args: { doctype: doctype },
		});
		series = r && r.message;
	} catch (e) {
		// A bypass role or an unconfigured branch is not an error — leave the picker alone.
	}
	if (series) {
		const df = frm.get_field("naming_series");
		const options = (df && df.df.options ? df.df.options.split("\n") : []).map((o) => o.trim());
		if (options.includes(series)) await frm.set_value("naming_series", series);
	}

	frappe.show_alert({
		message: series
			? __("Credit note — this will be numbered {0}", [series])
			: __("Return ticked — this is a credit note. Pick the invoice it is against."),
		indicator: "blue",
	});
};

// The same entry point from the Sales Invoice list, so a workspace shortcut to the
// returns list lands one click away from creating one. A Workspace Shortcut is config
// only — it cannot run this — which is why the list carries the button instead.
//
// 🔴 DO NOT MERGE INTO `frappe.listview_settings["Sales Invoice"]`. erpnext's own
// `sales_invoice_list.js` opens with a WHOLESALE ASSIGNMENT to that key, and a doctype's
// list bundle is fetched when the list is first opened — i.e. AFTER `app_include_js`.
// Whatever we merge in at boot is discarded, silently: the button simply never appears,
// with no error. Attach from the router instead, which runs after the view is built no
// matter which file loaded first.
// The "New Return" button, on every list where a return can start.
//
// 🔴 DO NOT MERGE INTO `frappe.listview_settings[...]`. erpnext's own list JS assigns
// that key wholesale and a doctype's list bundle loads AFTER app_include_js, so anything
// merged in at boot is discarded silently. Attach from the router instead.
//
// 🔴 AND DO NOT ADD IT ONCE BEHIND A "done" FLAG. On a COLD load the list view clears its
// own inner toolbar AFTER the first render, so a button added before that is wiped —
// measured: the add ran, the flag was set, and the toolbar came back empty, while an
// in-app route to the same list worked. Key on the button's presence in the DOM and keep
// re-checking for a few seconds, which also covers the bundle still being in flight.
const RETURN_LISTS = {
	// A blank one CAN be a return: is_return is editable on the invoices.
	"Sales Invoice": () => yht_custom.sales.new_return("Sales Invoice"),
	"Purchase Invoice": () => yht_custom.sales.new_return("Purchase Invoice"),
	// A blank one CANNOT: is_return is read_only + no_copy on the stock documents, so
	// these ask for the source note and run erpnext's mapper.
	"Delivery Note": () => yht_custom.sales.new_stock_return("Delivery Note"),
	"Purchase Receipt": () => yht_custom.sales.new_stock_return("Purchase Receipt"),
};

frappe.router.on("change", () => {
	const route = frappe.get_route() || [];
	if (route[0] !== "List") return;
	const doctype = route[1];
	const action = RETURN_LISTS[doctype];
	if (!action) return;

	const label = __("New Return");
	let tries = 0;
	const attach = () => {
		const lv = window.cur_list;
		if (lv && lv.doctype === doctype && lv.page && lv.page.inner_toolbar) {
			const present = lv.page.inner_toolbar
				.find("button")
				.filter((i, b) => b.innerText.trim() === label).length;
			if (!present) {
				lv.page.add_inner_button(label, action);
			}
		}
		if (++tries < 20) setTimeout(attach, 300);
	};
	attach();
});
