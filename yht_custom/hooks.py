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
	"/assets/yht_custom/js/branch_user_restrict.js?v=1",
]
app_include_css = "/assets/yht_custom/css/yht_custom.css?v=1"

# Prefer doctype_js over app_include_js: it takes effect without a `bench build`,
# which matters because builds are limited to the maintenance window.
doctype_js = {}
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
}

doc_events = {
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
}

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
				],
			]
		],
	},
	{"dt": "Module Profile", "filters": [["name", "in", ["Branch User"]]]},
]

# --------------------------------------------------------------------- migrate
after_migrate = "yht_custom.setup.after_migrate"
