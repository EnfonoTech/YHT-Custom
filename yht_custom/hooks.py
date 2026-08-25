app_name = "yht_custom"
app_title = "YHT Custom"
app_publisher = "Enfono Technologies"
app_description = "Customisation for YHT Trading — Kathoom Alkhobar Trading Co."
app_email = "sayanth@enfono.com"
app_license = "mit"

required_apps = ["frappe/erpnext"]

# ---------------------------------------------------------------- desk includes
# NOTE: files under /assets/yht_custom/js/ are served straight out of /assets and
# nginx sends them with ETag + Last-Modified but no Cache-Control, so a browser
# can keep a stale copy for hours after a deploy. BUMP the ?v= counter whenever
# one of these changes, or the deploy is invisible to anyone already loaded.
app_include_js = [
	"/assets/yht_custom/js/branch_user_restrict.js?v=7",
	"/assets/yht_custom/js/branch_user_forms.js?v=1",
	"/assets/yht_custom/js/sales_flow.js?v=1",
	"/assets/yht_custom/js/expense_invoice.js?v=5",
	"/assets/yht_custom/js/price_assist.js?v=6",
	"/assets/yht_custom/js/payment_assist.js?v=3",
	"/assets/yht_custom/js/simple_party.js?v=1",
	"/assets/yht_custom/js/rate_lock.js?v=2",
]
app_include_css = "/assets/yht_custom/css/yht_custom.css?v=7"

# Prefer doctype_js over app_include_js: it takes effect without a `bench build`,
# which matters because builds are limited to the maintenance window.
doctype_js = {
	"Item": "public/js/item_code_from_group.js",
	# The client's incumbent print buttons (Print PDF / Print Without LH, plus
	# Print Arabic with LH on Quotation). ONE file under four doctypes — it guards
	# its own registration so the handlers cannot stack up across a session.
	"Delivery Note": "public/js/katc_print_buttons.js",
	"Sales Invoice": "public/js/katc_print_buttons.js",
	"Sales Order": "public/js/katc_print_buttons.js",
	"Quotation": "public/js/katc_print_buttons.js",
}
doctype_list_js = {}

# ------------------------------------------------------------------- home pages
role_home_page = {
	"Branch User": "yht-dashboard",
	"Stock User": "yht-dashboard",
}

boot_session = "yht_custom.boot.boot_session"

# --------------------------------------------------------------- list filtering
# Branch users see only documents tied to their branch's warehouses. Every entry
# returns a SQL WHERE fragment; see branch_filters for the shared warehouse
# resolution.
# 🔴 See `sales_flow.make_sales_invoice_from_sales_order`. ERPNext's Sales Order
# mapper puts `ignore_permissions` in the third positional slot and `map_docs`
# puts the dialog's `args` there, so the desk's "Get Items From > Sales Order"
# 417s and silently leaves the invoice empty. Delivery Note is unaffected — its
# mapper has `args` in that slot.
override_whitelisted_methods = {
	"erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice": (
		"yht_custom.sales_flow.make_sales_invoice_from_sales_order"
	),
}


permission_query_conditions = {
	"Sales Invoice": "yht_custom.branch_filters.sales_invoice_query",
	"Purchase Invoice": "yht_custom.branch_filters.purchase_invoice_query",
	"Delivery Note": "yht_custom.branch_filters.delivery_note_query",
	"Purchase Receipt": "yht_custom.branch_filters.purchase_receipt_query",
	"Sales Order": "yht_custom.branch_filters.sales_order_query",
	"Quotation": "yht_custom.branch_filters.quotation_query",
	"Payment Entry": "yht_custom.branch_filters.payment_entry_query",
	"Stock Entry": "yht_custom.branch_filters.stock_entry_query",
	"Material Request": "yht_custom.branch_filters.material_request_query",
}

# ----------------------------------------------------------------- doc events
# Only for extending another app's DocType. Our own DocTypes keep their lifecycle
# in their controllers.
# Registered per doctype rather than against "*": a wildcard fires on every save
# in the system, including Version, Error Log and Activity Log rows, for hooks
# that only ever apply to these twelve.
_BRANCH_DEFAULT_EVENTS = {
	"before_validate": "yht_custom.branch_defaults.apply_branch_defaults",
	"before_insert": "yht_custom.branch_defaults.set_naming_series_from_branch",
	# The boundary that makes the ignore_user_permissions Property Setters safe.
	# Runs on validate so it catches the desk, REST, imports and Server Scripts.
	"validate": "yht_custom.branch_guard.validate_branch_scope",
}

doc_events = {
	# Saudi national address (plan 5.9). Address is shared by Customer and
	# Supplier, so one registration covers both parties.
	"Address": {
		"validate": "yht_custom.saudi_address.validate",
		"before_insert": "yht_custom.saudi_address.before_insert",
	},
	# Item code generation — before_insert, because frappe runs it BEFORE
	# set_new_name() and ERPNext's Item.autoname ends with name = item_code.
	"Item": {"before_insert": "yht_custom.item_naming.set_item_code_from_group"},
}

# --- flow policy (Step 5) -------------------------------------------------
# Order matters within a hook: branch defaults run first, then the flow policy
# overrides what it must. expense_invoice.set_expense_series deliberately runs
# after set_naming_series_from_branch so an expense invoice takes the expense
# series rather than the branch's purchase series.
_DISCOUNT_EVENTS = {
	doctype: {"validate": "yht_custom.discount_totals.set_line_discount_total"}
	for doctype in ("Sales Invoice", "Sales Order", "Delivery Note", "Quotation")
}

_FLOW_EVENTS = {
	"Sales Invoice": {
		"before_validate": "yht_custom.sales_flow.enforce_delivery_note_route",
		# Item 5: a rate fetched from a Sales Order or Delivery Note is not
		# editable here. The JS makes the cell read-only; this is the boundary.
		"validate": "yht_custom.rate_lock.enforce_fetched_rate",
	},
	"Delivery Note": {
		"validate": "yht_custom.sales_flow.validate_delivery_note",
		"on_update_after_submit": "yht_custom.sales_flow.lock_submitted_delivery_note",
	},
	"Purchase Invoice": {
		"before_validate": [
			"yht_custom.sales_flow.enforce_purchase_receipt_route",
			"yht_custom.expense_invoice.before_validate",
		],
		"validate": "yht_custom.expense_invoice.validate",
		"before_insert": "yht_custom.expense_invoice.set_expense_series",
		"on_submit": "yht_custom.expense_invoice.on_submit",
	},
}

doc_events.update({
	doctype: dict(_BRANCH_DEFAULT_EVENTS)
	for doctype in (
		"Sales Invoice",
		"Purchase Invoice",
		"Delivery Note",
		"Purchase Receipt",
		"Sales Order",
		"Purchase Order",
		"Quotation",
		"Payment Entry",
		"Journal Entry",
		"Stock Entry",
		"Material Request",
		"Stock Reconciliation",
	)
})


def _merge_events(base: dict, extra: dict) -> dict:
	"""Merge two doc_events maps, combining handlers on a shared event.

	A plain dict.update would drop the branch hooks wherever the flow policy also
	registers on that doctype — Purchase Invoice registers on before_validate in
	both, and losing the branch cost-centre override there would be silent.
	"""
	for doctype, events in extra.items():
		target = base.setdefault(doctype, {})
		for event, handler in events.items():
			handlers = handler if isinstance(handler, list) else [handler]
			existing = target.get(event)
			if not existing:
				target[event] = handlers if len(handlers) > 1 else handlers[0]
				continue
			existing_list = existing if isinstance(existing, list) else [existing]
			target[event] = existing_list + handlers
	return base


doc_events = _merge_events(doc_events, _FLOW_EVENTS)
doc_events = _merge_events(doc_events, _DISCOUNT_EVENTS)

# -------------------------------------------------------------------- fixtures
# A fixture needs BOTH the entry here AND the record itself — a name missing from
# this filter list is silently not exported.
fixtures = [
	{"dt": "Role", "filters": [["name", "in", ["Branch User"]]]},
	{
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					"Branch-custom_doc_prefix",
					"Branch-custom_branch_name_ar",
					"Branch-custom_letter_head",
					"Branch-custom_naming_series_table",
					"Item Group-custom_item_code_prefix",
					"Purchase Invoice-custom_is_expense_invoice",
					"Purchase Invoice-custom_expense_head",
					"Sales Order-custom_print_as",
					"Sales Invoice-custom_payment_mode",
					"Sales Invoice-custom_total_line_item_discount",
					"Sales Order-custom_total_line_item_discount",
					"Delivery Note-custom_total_line_item_discount",
					"Quotation-custom_total_line_item_discount",
					"Address-custom_additional_number",
					"Address-custom_unit_number",
					"Address-custom_short_address",
					"Employee-custom_is_saudi_national",
					"Employee-custom_gosi_number",
					"Employee-custom_iqama_number",
				],
			]
		],
	},
	{"dt": "Module Profile", "filters": [["name", "in", ["Branch User"]]]},
]

# ---------------------------------------------------------------------- jinja
# Print formats call these. Without the hook, a print format cannot reach app
# code at all and every format ends up duplicating the same header markup —
# which is how the legacy site accumulated 32 Delivery Note formats.
# The hook does NOT support "alias:path" — each function is registered under its
# own __name__, and every app's jinja methods share ONE namespace. Hence the
# yht_ prefix on the functions themselves.
jinja = {
	"methods": [
		"yht_custom.print_helpers.yht_branch_header",
		"yht_custom.print_helpers.yht_party",
		"yht_custom.print_helpers.yht_money",
		"yht_custom.print_helpers.yht_date",
		"yht_custom.print_helpers.yht_item_ar",
		"yht_custom.print_helpers.yht_so_title",
		"yht_custom.print_helpers.yht_line_discount",
		"yht_custom.print_helpers.yht_discount_total",
		"yht_custom.print_helpers.yht_currency",
		# The KATC client prints. Every path here is resolved when the jinja
		# environment is built, so one that does not import 500s EVERY website page,
		# /login included, until the workers reload (gotcha 25).
		"yht_custom.print_helpers.yht_katc_lh",
		"yht_custom.print_helpers.yht_katc_email",
		"yht_custom.print_helpers.yht_katc_spacer_pt",
		"yht_custom.print_helpers.yht_company_vat",
		"yht_custom.print_helpers.yht_party_vat",
		"yht_custom.print_helpers.yht_row_taxes",
		"yht_custom.print_helpers.yht_national_address",
		"yht_custom.print_helpers.yht_sales_person",
		"yht_custom.print_helpers.yht_creator_contact",
		"yht_custom.print_helpers.yht_zatca_qr",
		"yht_custom.print_helpers.yht_bank_details",
	],
}

# --------------------------------------------------------------------- migrate
after_migrate = "yht_custom.setup.after_migrate"
