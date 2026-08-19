// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Sales-side payment assist (MoM §5.6): the cash/credit decision, the customer's
// outstanding position, the credit-limit warning, and the tender dialog.
//
// TWO DELIBERATE DIFFERENCES FROM RMAX, both to avoid known defects:
//
//   1. THE DIALOG FIRES AFTER SUBMIT, NOT AT SAVE.
//      RMAX opens it on a draft and then refuses to let the document save until
//      the full amount is allocated. That is wrong whenever the operator does not
//      yet know the split, and there is no discoverable escape except changing
//      Payment Mode away from Cash. Here the invoice saves and submits normally;
//      the dialog opens once there is something real to pay against, and closing
//      it leaves a perfectly valid unpaid invoice. `Collect Payment` in the
//      toolbar reopens it any time.
//
//   2. RETURNS ARE EXCLUDED.
//      RMAX's gate never checks `is_return` — the string does not appear in its
//      popup file — so the dialog also appears on credit notes, labelled
//      "Enter Payment Amounts" against a positive "Invoice Total" while the money
//      is actually going out. Logged as an open defect in RMAX's own ROADMAP.md.
//      This site already holds 99 returns, so it would land on day one.
//
// The server never sends an account number, an IBAN or a GL account code to this
// file — see yht_custom/api/payment_assist.py for why that mattered.

frappe.provide("yht_custom.payment");

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		yht_custom.payment.show_customer_position(frm);
		yht_custom.payment.add_collect_button(frm);
	},

	customer(frm) {
		yht_custom.payment.show_customer_position(frm);
	},

	custom_payment_mode(frm) {
		yht_custom.payment.show_customer_position(frm);
	},

	// `on_submit`, NOT `after_submit`.
	//
	// `after_submit` is a key on `frappe.route_hooks` (frappe form.js:851), not a form script
	// event, so a handler registered under that name is never called and the dialog silently
	// never opened. The invoice submitted fine and the Collect Payment button appeared, which
	// made it look like the feature worked — only the automatic open was missing.
	on_submit(frm) {
		// A beat, so the submit alert and the docstatus re-render land first, and re-check
		// afterwards rather than trusting the doc state at trigger time.
		setTimeout(() => {
			if (yht_custom.payment.wants_tender(frm)) yht_custom.payment.open_tender(frm);
		}, 600);
	},

	before_save(frm) {
		return yht_custom.payment.warn_over_credit_limit(frm);
	},
});

// ------------------------------------------------------------ customer position

yht_custom.payment.status_cache = {};

yht_custom.payment.fetch_status = function (frm) {
	if (!frm.doc.customer || !frm.doc.company) return Promise.resolve(null);
	const key = `${frm.doc.customer}::${frm.doc.company}`;
	if (yht_custom.payment.status_cache[key]) {
		return Promise.resolve(yht_custom.payment.status_cache[key]);
	}
	return frappe
		.call({
			method: "yht_custom.api.payment_assist.get_customer_payment_status",
			args: { customer: frm.doc.customer, company: frm.doc.company },
		})
		.then((r) => {
			const status = r.message || null;
			if (status) yht_custom.payment.status_cache[key] = status;
			return status;
		});
};

// The customer's exposure, on the sales screen, before the sale is committed.
yht_custom.payment.show_customer_position = function (frm) {
	if (!frm.doc.customer) return;
	yht_custom.payment.fetch_status(frm).then((status) => {
		if (!status) return;
		const money = (v) => format_currency(v || 0, frm.doc.currency);

		const outstanding = flt(status.outstanding);
		frm.dashboard.add_indicator(
			__("Outstanding: {0}", [money(outstanding)]),
			outstanding > 0 ? "orange" : "green"
		);

		if (status.has_limit) {
			const exposure = outstanding + flt(frm.doc.grand_total);
			const over = exposure - flt(status.credit_limit);
			frm.dashboard.add_indicator(
				__("Credit limit: {0}", [money(status.credit_limit)]),
				over > 0 ? "red" : "blue"
			);
		}
	});
};

// ------------------------------------------------------------- credit-limit gate
//
// B5 was answered "warn, allow override", so this resolves rather than rejects.
// `bypass_credit_limit_check` on the customer's own limit row silences it, which
// is ERPNext's existing convention for the same decision.
//
// Dormant until limits exist: measured 0 Customer Credit Limit rows on this site.

yht_custom.payment.warn_over_credit_limit = function (frm) {
	if (frm.doc.custom_payment_mode !== "Credit") return;
	if (frm.doc.is_return) return;
	if (!frm.doc.customer || !flt(frm.doc.grand_total)) return;

	return yht_custom.payment.fetch_status(frm).then((status) => {
		if (!status || !status.has_limit || status.bypass_credit_limit_check) return;

		const money = (v) => format_currency(v || 0, frm.doc.currency);
		// The invoice's own total counts only while it is still a draft; once
		// submitted it is already inside `outstanding`.
		const pending = frm.doc.docstatus === 0 ? flt(frm.doc.grand_total) : 0;
		const exposure = flt(status.outstanding) + pending;
		if (exposure <= flt(status.credit_limit)) return;

		frappe.show_alert(
			{
				message: __("{0} would be {1} over their credit limit.", [
					frappe.utils.escape_html(frm.doc.customer_name || frm.doc.customer),
					money(exposure - flt(status.credit_limit)),
				]),
				indicator: "red",
			},
			10
		);
	});
};

// ------------------------------------------------------------------- tender flow

yht_custom.payment.wants_tender = function (frm) {
	return (
		frm.doc.custom_payment_mode === "Cash" &&
		!frm.doc.is_return &&
		frm.doc.docstatus === 1 &&
		flt(frm.doc.outstanding_amount) > 0
	);
};

yht_custom.payment.add_collect_button = function (frm) {
	// ERPNext's own Create > Payment is a dead end for a branch user, so replace it rather
	// than leave two buttons where one throws.
	//
	// It calls `get_payment_entry`, which sets `pe.bank_account` from the company default and
	// then hits `has_permission("Bank Account", "read", throw=True)` — a bare
	//     "User … does not have doctype access via role permission for document Bank Account"
	// with nothing on screen explaining which document. Granting that read would hand every
	// branch operator the account number and IBAN of every company account, so instead the
	// native action is removed for restricted users and `Collect Payment` takes its place.
	// See yht_custom/api/payment_assist.py for the full trace.
	if (frappe.boot && frappe.boot.yht_branch_restricted && frm.doc.docstatus === 1) {
		frm.remove_custom_button("Payment", "Create");
	}

	if (!yht_custom.payment.wants_tender(frm)) return;
	frm.add_custom_button(__("Collect Payment"), () => yht_custom.payment.open_tender(frm));
};

yht_custom.payment.open_tender = function (frm) {
	frappe.call({
		method: "yht_custom.api.payment_assist.get_branch_payment_modes",
		args: { company: frm.doc.company },
		callback(r) {
			const modes = r.message || [];
			if (!modes.length) {
				frappe.msgprint({
					title: __("No payment modes available"),
					message: __(
						"No Mode of Payment is set up with a default account for {0}, or none is allowed for your branch. Ask your administrator to configure the branch's payment modes.",
						[frappe.utils.escape_html(frm.doc.company)]
					),
					indicator: "orange",
				});
				return;
			}
			yht_custom.payment.tender_dialog(frm, modes);
		},
	});
};

yht_custom.payment.tender_dialog = function (frm, modes) {
	const outstanding = flt(frm.doc.outstanding_amount);
	const money = (v) => format_currency(v || 0, frm.doc.currency);

	const fields = [
		{
			fieldtype: "Currency",
			fieldname: "outstanding",
			label: __("Amount Due"),
			default: outstanding,
			read_only: 1,
		},
		{ fieldtype: "Section Break" },
	];

	// One row per mode. Cash types first — that is what a counter reaches for.
	modes.forEach((mode, i) => {
		fields.push({
			fieldtype: "Currency",
			fieldname: `amount_${i}`,
			label: mode.mode_of_payment,
			default: 0,
		});
	});

	fields.push(
		{ fieldtype: "Section Break" },
		{ fieldtype: "HTML", fieldname: "summary" }
	);

	const dialog = new frappe.ui.Dialog({
		title: __("Collect Payment"),
		fields: fields,
		primary_action_label: __("Record Payment"),
		primary_action(values) {
			const rows = modes
				.map((mode, i) => ({
					mode_of_payment: mode.mode_of_payment,
					amount: flt(values[`amount_${i}`]),
				}))
				.filter((row) => row.amount > 0);

			if (!rows.length) {
				frappe.msgprint(__("Enter an amount against at least one mode of payment."));
				return;
			}

			const total = rows.reduce((sum, row) => sum + row.amount, 0);
			if (total - outstanding > 0.01) {
				frappe.msgprint(
					__("Tendered {0} is more than the {1} due.", [money(total), money(outstanding)])
				);
				return;
			}

			dialog.get_primary_btn().prop("disabled", true);
			frappe.call({
				method: "yht_custom.api.payment_assist.collect_payment",
				args: { sales_invoice: frm.doc.name, payments: rows },
				freeze: true,
				freeze_message: __("Recording payment…"),
				callback(r) {
					dialog.hide();
					const created = r.message || [];
					frappe.show_alert(
						{
							message:
								created.length === 1
									? __("Payment {0} recorded.", [created[0]])
									: __("{0} payments recorded.", [created.length]),
							indicator: "green",
						},
						7
					);
					frm.reload_doc();
				},
				error() {
					dialog.get_primary_btn().prop("disabled", false);
				},
			});
		},
		secondary_action_label: __("Pay Later"),
		secondary_action() {
			dialog.hide();
		},
	});

	// Running total, so a split is checkable before it is committed.
	const refresh_summary = () => {
		const total = modes.reduce(
			(sum, mode, i) => sum + flt(dialog.get_value(`amount_${i}`)),
			0
		);
		const balance = flt(outstanding - total, 2);
		const colour = balance < -0.01 ? "red" : balance > 0.01 ? "orange" : "green";
		dialog.fields_dict.summary.$wrapper.html(`
			<div style="display:flex;justify-content:space-between;font-weight:600">
				<span>${__("Tendered")}</span><span>${money(total)}</span>
			</div>
			<div style="display:flex;justify-content:space-between;color:var(--text-muted)">
				<span>${balance < 0 ? __("Over by") : __("Still due")}</span>
				<span style="color:var(--${colour}-500, inherit)">${money(Math.abs(balance))}</span>
			</div>
		`);
	};

	modes.forEach((mode, i) => {
		dialog.fields_dict[`amount_${i}`].df.onchange = refresh_summary;
	});

	dialog.show();

	// A single-mode branch has exactly one sensible answer — prefill it, and the
	// operator either confirms or edits. With several modes, prefilling the first
	// would be a guess.
	if (modes.length === 1) {
		dialog.set_value("amount_0", outstanding);
	}
	refresh_summary();
};
