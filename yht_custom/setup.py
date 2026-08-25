# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Idempotent provisioning, run on every ``after_migrate``.

Everything here must be safe to run repeatedly and must never clobber a manual
change an implementer made on the site.
"""

import frappe
from frappe.utils import cint

from yht_custom.setup_branch_series import setup_branch_series
from yht_custom.expense_invoice import setup_expense_invoice
from yht_custom.form_layout import setup_form_layout
from yht_custom.site_defaults import setup_site_defaults
from yht_custom.setup_property_setters import setup_ignore_user_permissions
from yht_custom.discount_totals import setup_discount_grid_columns
from yht_custom.saudi_address import ADDRESS_CUSTOM_FIELDS
from yht_custom.letterhead import setup_branch_letterheads
from yht_custom.katc_letterhead import setup_katc_letterhead
from yht_custom.hr_setup import setup_hr
from yht_custom.sales_assist import setup_sales_assist_columns
from yht_custom.workspace_shortcuts import setup_new_shortcuts

#: What a Branch User may touch. Per the MoM document set — Quotation, Sales
#: Order, Delivery Note, Sales Invoice, Purchase Receipt, Purchase Invoice,
#: Customer, Item, Payment Entry. Material Request and inter-branch transfer are
#: deliberately absent.
#:
#: `cancel` is 0 everywhere: cancellation is reserved for one designated user.
BRANCH_USER_PERMISSIONS = [
	# --- transacting ---
	{"parent": "Quotation", "read": 1, "write": 1, "create": 1, "submit": 1, "print": 1, "email": 1, "report": 1, "export": 1},
	{"parent": "Sales Order", "read": 1, "write": 1, "create": 1, "submit": 1, "print": 1, "email": 1, "report": 1, "export": 1},
	{"parent": "Delivery Note", "read": 1, "write": 1, "create": 1, "submit": 1, "print": 1, "email": 1, "report": 1, "export": 1},
	{"parent": "Sales Invoice", "read": 1, "write": 1, "create": 1, "submit": 1, "print": 1, "email": 1, "report": 1, "export": 1},
	{"parent": "Purchase Receipt", "read": 1, "write": 1, "create": 1, "submit": 1, "print": 1, "report": 1, "export": 1},
	{"parent": "Purchase Invoice", "read": 1, "write": 1, "create": 1, "submit": 1, "print": 1, "report": 1, "export": 1},
	{"parent": "Payment Entry", "read": 1, "write": 1, "create": 1, "submit": 1, "print": 1, "report": 1, "export": 1},
	# --- masters they maintain ---
	{"parent": "Customer", "read": 1, "write": 1, "create": 1, "print": 1, "email": 1, "report": 1, "export": 1},
	{"parent": "Address", "read": 1, "write": 1, "create": 1, "print": 1, "report": 1, "export": 1},
	{"parent": "Contact", "read": 1, "write": 1, "create": 1, "print": 1, "report": 1, "export": 1},
	# --- masters they read only (item creation is centralised) ---
	{"parent": "Item", "read": 1, "print": 1, "report": 1, "export": 1},
	{"parent": "Item Group", "read": 1, "report": 1},
	{"parent": "Item Price", "read": 1, "report": 1},
	{"parent": "Price List", "read": 1, "report": 1},
	{"parent": "Supplier", "read": 1, "report": 1},
	{"parent": "Warehouse", "read": 1, "report": 1},
	{"parent": "Cost Center", "read": 1, "report": 1},
	{"parent": "Company", "read": 1},
	{"parent": "Branch", "read": 1, "report": 1},
	{"parent": "Account", "read": 1, "report": 1},
	{"parent": "Customer Group", "read": 1},
	{"parent": "Supplier Group", "read": 1},
	{"parent": "Territory", "read": 1},
	{"parent": "UOM", "read": 1},
	{"parent": "Brand", "read": 1},
	{"parent": "Mode of Payment", "read": 1},
	# Party Type — 4 rows (Shareholder / Employee / Supplier / Customer), no sensitive content.
	#
	# WHY IT WAS MISSED, AND WHY A LINK-TARGET SWEEP WILL MISS IT AGAIN:
	# `Payment Entry.party_type` and `Journal Entry Account.party_type` are declared
	# `Link -> DocType`, NOT `Link -> Party Type`. The picker is narrowed at runtime by a
	# wired search query,
	#     query: "erpnext.setup.doctype.party_type.party_type.get_party_type"
	# and `frappe.desk.search.search_link` permission-checks the doctype the QUERY
	# searches. So a sweep that walks declared `options` sees `DocType` and never
	# discovers Party Type at all — the declared option lies about what gets read.
	# Symptom: a bare "No permission for Party Type" the moment a branch user opens a
	# Payment Entry. `read` is what fixes it — search_widget resolves the check as
	#     ptype = "select" if frappe.only_has_select_perm(doctype) else "read"
	# so `select` is the alternative for a select-only role, not an extra requirement.
	# Both are granted here anyway: this is a 4-row reference table and a picker that
	# works either way is one less thing to diagnose.
	# test_branch_smoke.py now exercises the wired queries directly.
	{"parent": "Party Type", "read": 1, "select": 1},
	{"parent": "Sales Taxes and Charges Template", "read": 1},
	{"parent": "Purchase Taxes and Charges Template", "read": 1},
	{"parent": "Payment Terms Template", "read": 1},
	{"parent": "Terms and Conditions", "read": 1},
	# --- settings the forms read on load; without these the form fails to open ---
	{"parent": "Selling Settings", "read": 1},
	{"parent": "Buying Settings", "read": 1},
	{"parent": "Stock Settings", "read": 1},
	{"parent": "Accounts Settings", "read": 1},
	# --- the dashboard page needs read on Page ---
	{"parent": "Page", "read": 1},
	# --- the dashboard's report tiles ------------------------------------------
	# A report needs BOTH: read on its `ref_doctype`'s underlying ledger, and the
	# role listed in `Report.roles` (see setup_report_roles below). Doctype-level
	# read alone passes has_permission and still fails the report route, which is
	# why the tiles opened "You don't have access to Report: …".
	{"parent": "GL Entry", "read": 1, "report": 1},
	{"parent": "Stock Ledger Entry", "read": 1, "report": 1},
	{"parent": "Bin", "read": 1, "report": 1},
	{"parent": "Report", "read": 1},
	# Accounts Receivable Summary reaches further than its ref_doctype suggests:
	# accounts_receivable.py:517 does frappe.get_list("Journal Entry") for invoices
	# booked via a JE, and the report also joins Payment Ledger Entry. Without both
	# it dies on a bare PermissionError with no message. Read-only; GL Entry read
	# (already granted above) is strictly more revealing than either.
	{"parent": "Journal Entry", "read": 1, "report": 1},
	{"parent": "Payment Ledger Entry", "read": 1, "report": 1},
	# --- support masters the transacting FORMS read on load -------------------
	# Added after a live sweep: 51 link targets reachable from the branch forms
	# were unreadable, of which these are the ones a KSA trading flow actually
	# touches. Granting all 51 would hand a branch operator Assets, BOMs,
	# Timesheets, POS and the whole CRM for no reason.
	#
	# `Tax Category` was the reported failure — "You do not have Read or Select
	# Permissions for Tax Category" on every Sales Invoice, because ERPNext reads
	# the customer's tax category while setting missing values.
	# `Item Tax Template` is read per ITEM ROW: ksa_compliance fetches
	# `custom_zatca_item_tax_category` through it, so ZATCA needs it.
	{"parent": "Tax Category", "read": 1},
	{"parent": "Item Tax Template", "read": 1, "report": 1},
	{"parent": "Payment Term", "read": 1},
	{"parent": "Currency", "read": 1},
	{"parent": "Incoterm", "read": 1},
	{"parent": "Pricing Rule", "read": 1, "report": 1},
	{"parent": "Shipping Rule", "read": 1},
	{"parent": "Sales Person", "read": 1},
	{"parent": "Sales Partner", "read": 1},
	{"parent": "Purchase Order", "read": 1, "report": 1},
	{"parent": "Material Request", "read": 1, "report": 1},
	{"parent": "Batch", "read": 1, "report": 1},
	{"parent": "Serial and Batch Bundle", "read": 1, "report": 1},
	{"parent": "Driver", "read": 1},
	# NOTE: `Bank Account` is deliberately ABSENT. Granting read there is what
	# unblocks ERPNext's "Create > Payment" button on a Sales Invoice, but read on
	# Bank Account exposes the account number and IBAN — there is no permlevel
	# split on that doctype — so it is a client decision, not a code one.
	# Tracked as the expected failure in tests/test_sales_cycle.py.
	#
	# ⚠️ ONE CONSEQUENCE OF THAT DECISION, WRITTEN DOWN RATHER THAN LEFT IMPLICIT.
	# `print_helpers.yht_bank_details()` reads the designated receiving account with
	# `frappe.db.get_value` precisely so the KATC formats stay printable for a role
	# denied that read. It takes no arguments and applies no permission check of its
	# own, and a `jinja` hook method lands in the SITE-WIDE template namespace — not
	# only in the KATC print formats. So anyone who can author a template
	# (Notification, Email Template, Web Page, Print Format Builder HTML) can render
	# the IBAN regardless of their `Bank Account` permission.
	#
	# That is the approved trade (Q5: one designated receiving account prints on a
	# customer-facing quotation), and it is bounded because `Branch User` holds NO
	# create right on any of those four doctypes: none of them appears in this list,
	# and the role is in no standard DocPerm for them either. Re-check that sentence
	# before adding any of the four here.
]

#: Every permission flag a Custom DocPerm row carries that we are willing to set.
#:
#: `select` and `if_owner` were absent here for a while, and because
#: `_upsert_custom_docperm` builds its values dict from THIS tuple, the two flags were
#: read out of the standard DocPerm by `preserve_standard_docperms` and then silently
#: thrown away. Measured damage before the fix: 5 rows across `Address` (if_owner, role
#: All), `Customer Group` / `Territory` (select, role Customer) and `Item` / `Item Group`
#: (select, role Desk User) — i.e. this app quietly narrowed permissions for roles that
#: have nothing to do with branch scoping. `repair_mirrored_perm_flags` heals it.
#:
#: `select` also matters in its own right: `frappe.desk.search.search_link` wants it, so a
#: role without it cannot use a Link picker even when it can read the doctype.
PERM_FIELDS = (
	"read", "write", "create", "submit", "cancel", "delete",
	"report", "export", "print", "email", "share", "amend",
	"select", "if_owner",
)

BRANCH_USER_ROLE = "Branch User"

#: Client sheet items 13 and 14. The sheet listed six roles "details will update
#: later"; the client has since said they only need this one. It is a SUPERSET of
#: Branch User — same branch scoping, same doctypes — plus the one thing that
#: makes it a manager: cancelled documents stay visible (item 14).
BRANCH_MANAGER_ROLE = "Branch Manager"
MODULE_PROFILE = "Branch User"


#: Provisioning steps, in dependency order. Each is independent, so one failing
#: must not abort the rest — a DocumentLockedError on the Module Profile used to
#: swallow the Property Setter and naming-series steps entirely, which is far
#: worse than the original failure.
PROVISIONING_STEPS = (
	"ensure_branch_user_role",
	"ensure_branch_custom_fields",
	"preserve_standard_docperms",
	"setup_branch_user_permissions",
	"ensure_module_profile",
	"setup_ignore_user_permissions",
	"setup_expense_invoice",
	"setup_branch_series",
	"setup_branch_letterheads",
	"setup_katc_letterhead",
	"setup_default_print_formats",
	"setup_form_layout",
	"setup_discount_grid_columns",
	"setup_sales_assist_columns",
	"setup_new_shortcuts",
	"setup_site_defaults",
	"setup_report_roles",
	"setup_branch_payment_modes",
	"repair_mirrored_perm_flags",
	"run_dashboard_reports_inline",
	"setup_hr",
)


def after_migrate():
	"""Entry point wired from hooks.py.

	Runs every provisioning step, logging and continuing past any that fails.
	The alternative — letting the first exception propagate — means a transient
	lock on one document silently leaves the permission layer half-built.
	"""
	import sys

	failures = []
	for step in PROVISIONING_STEPS:
		func = globals().get(step) or _imported(step)
		try:
			func()
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			failures.append(f"{step}: {type(e).__name__}: {e}")
			frappe.log_error(frappe.get_traceback(), f"yht_custom after_migrate: {step}")
			print(f"  yht_custom after_migrate: {step} FAILED — {type(e).__name__}: {e}", file=sys.stderr)

	if failures:
		# Loud but non-fatal: migrate should still finish so the rest of the
		# deploy completes, but nobody should be able to miss this.
		print("\n  yht_custom after_migrate completed WITH FAILURES:", file=sys.stderr)
		for f in failures:
			print(f"    - {f}", file=sys.stderr)
	return {"failures": failures}


def _imported(name):
	"""Resolve a step that lives in another module."""
	return {
		"setup_ignore_user_permissions": setup_ignore_user_permissions,
		"setup_expense_invoice": setup_expense_invoice,
		"setup_branch_series": setup_branch_series,
		"setup_default_print_formats": setup_default_print_formats,
		"setup_form_layout": setup_form_layout,
		"setup_site_defaults": setup_site_defaults,
		"setup_discount_grid_columns": setup_discount_grid_columns,
		"setup_branch_letterheads": setup_branch_letterheads,
		"setup_katc_letterhead": setup_katc_letterhead,
		"setup_hr": setup_hr,
		"setup_sales_assist_columns": setup_sales_assist_columns,
		"setup_new_shortcuts": setup_new_shortcuts,
	}[name]


# ------------------------------------------------------------------------ role


def ensure_branch_user_role():
	"""Both branch roles. Idempotent.

	`Branch Manager` is deliberately a separate ROLE rather than a flag on the
	user: item 14 ("cancelled file only view role branch manager") is a
	permission question, and `branch_filters` has to be able to answer it in SQL
	without loading a User document per query.
	"""
	for role_name in (BRANCH_USER_ROLE, BRANCH_MANAGER_ROLE):
		if frappe.db.exists("Role", role_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 1,
				"is_custom": 1,
			}
		).insert(ignore_permissions=True)


# --------------------------------------------------------------- custom fields


#: Fields the branch machinery hangs off. Shipped here rather than as a fixture
#: file so a fresh install needs no manual import step; the fixture entry in
#: hooks.py keeps them exportable.
BRANCH_CUSTOM_FIELDS = [
	{
		"fieldname": "custom_doc_prefix",
		"label": "Document Prefix",
		"fieldtype": "Data",
		"insert_after": "branch",
		"description": "Document number prefix for this branch, e.g. <code>KS</code>. Drives every per-branch naming series.",
	},
	{
		"fieldname": "custom_branch_name_ar",
		"label": "Branch Name (Arabic)",
		"fieldtype": "Data",
		"insert_after": "custom_doc_prefix",
		"description": "Used in the bilingual letterhead and ZATCA print formats.",
	},
	{
		"fieldname": "custom_letter_head",
		"label": "Letter Head",
		"fieldtype": "Link",
		"options": "Letter Head",
		"insert_after": "custom_branch_name_ar",
		"description": "Optional override. When empty the print format resolves <code>YHT - &lt;Branch&gt;</code>, then the master.",
	},
	{
		"fieldname": "custom_naming_series_table",
		"label": "Naming Series",
		"fieldtype": "Table",
		"options": "Branch Naming Series",
		"insert_after": "custom_letter_head",
		"description": "Seeded automatically from the Document Prefix on every migrate. Rarely edited by hand.",
	},
]


#: MoM 2.3 — one Sales Order that prints as Quotation, Proforma Invoice or Sales
#: Order, instead of three documents that drift apart.
SALES_ORDER_CUSTOM_FIELDS = [
	{
		"fieldname": "custom_print_as",
		"label": "Print As",
		"fieldtype": "Select",
		"options": "Sales Order\nQuotation\nProforma Invoice",
		"default": "Sales Order",
		"insert_after": "order_type",
		"allow_on_submit": 1,
		"print_hide": 1,
		"description": "Switches the printed title. The document itself is unchanged.",
	},
]

#: Cash-or-credit, the decision the tender dialog hangs off (MoM 5.6).
#:
#: Defaults to Credit, not Cash. A Cash default would open the tender dialog on
#: every invoice an operator submits, including the ones they never intended to
#: collect against, and the safe accounting reading of "invoice raised" is that
#: the money has not arrived yet. `allow_on_submit` because collection is decided
#: at the counter, sometimes after the invoice is already submitted.
SALES_INVOICE_CUSTOM_FIELDS = [
	{
		"fieldname": "custom_payment_mode",
		"label": "Payment Mode",
		"fieldtype": "Select",
		"options": "Credit\nCash",
		"default": "Credit",
		"insert_after": "due_date",
		"allow_on_submit": 1,
		"in_standard_filter": 1,
		"description": "Cash opens the payment dialog once the invoice is submitted.",
	},
]

#: Consolidated item-wise discount, printed under the totals block (MoM §2.3).
#:
#: Read-only and computed: `discount_totals.set_line_discount_total` writes it on
#: validate. The print formats do NOT read it — they call the Jinja helper, which
#: recomputes from the rows, so documents submitted before this field existed
#: still print a correct total. The field exists so the number can be filtered and
#: reported on, and it carries `allow_on_submit` because a Delivery Note can be
#: amended after submit and the stored copy would otherwise go stale.
DISCOUNT_TOTAL_FIELD = {
	"fieldname": "custom_total_line_item_discount",
	"label": "Total Item Discount",
	"fieldtype": "Currency",
	"options": "currency",
	"read_only": 1,
	"allow_on_submit": 1,
	"no_copy": 0,
	"print_hide": 1,
	"description": "Sum of the discount given on the item rows. The header discount is separate.",
}


def _discount_total_field(insert_after):
	return [dict(DISCOUNT_TOTAL_FIELD, insert_after=insert_after)]


#: Client sheet item 10 wants update-stock, price list and store sitting together
#: immediately above the item table. On **Sales Invoice and Quotation there is no
#: section break between the Currency and Price List accordion and the items
#: table** — Sales Order, Purchase Invoice and Purchase Receipt all have
#: `sec_warehouse`, those two do not.
#:
#: 🔴 That matters because Step 4 HIDES `currency_and_price_list`, and hiding a
#: Section Break hides everything up to the NEXT one. Moving the trio to sit just
#: before `items_section` therefore moved it INSIDE the hidden span — update
#: stock, the price list and the warehouse all silently disappeared from Sales
#: Invoice. Caught by the Step 4 regression test, which exists for exactly this.
#:
#: So the trio gets its own section break to live under. It is a Custom Field
#: rather than a Property Setter because there is no existing break to repoint.
STOCK_PRICING_SECTION = {
	"fieldname": "custom_stock_pricing_section",
	"label": "Stock & Pricing",
	"fieldtype": "Section Break",
	"insert_after": "ignore_pricing_rule",
	"collapsible": 0,
}

#: Prefix that drives item-group-wise item code generation (see item_naming.py).
ITEM_GROUP_CUSTOM_FIELDS = [
	{
		"fieldname": "custom_item_code_prefix",
		"label": "Item Code Prefix",
		"fieldtype": "Data",
		"insert_after": "item_group_name",
		"description": "Letter prefix for auto-generated item codes in this group, e.g. <code>BV</code> gives <code>BV-0001</code>. Leave empty to keep entering item codes by hand.",
	},
]


def ensure_branch_custom_fields():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(
		{
			"Branch": BRANCH_CUSTOM_FIELDS,
			"Item Group": ITEM_GROUP_CUSTOM_FIELDS,
			"Sales Order": SALES_ORDER_CUSTOM_FIELDS + _discount_total_field("discount_amount")
			+ [dict(STOCK_PRICING_SECTION)],
			"Sales Invoice": SALES_INVOICE_CUSTOM_FIELDS + _discount_total_field("discount_amount")
			+ [dict(STOCK_PRICING_SECTION)],
			"Delivery Note": _discount_total_field("discount_amount") + [dict(STOCK_PRICING_SECTION)],
			"Purchase Invoice": [dict(STOCK_PRICING_SECTION)],
			"Purchase Receipt": [dict(STOCK_PRICING_SECTION)],
			"Quotation": _discount_total_field("discount_amount"),
			# ksa_compliance already ships custom_building_number and custom_area,
			# and its own mapping decides which fieldnames reach the ZATCA XML.
			# These three are the ones it does not provide.
			"Address": ADDRESS_CUSTOM_FIELDS,
			# Item 10's visible home for update-stock / price list / store.
			"Quotation": [dict(STOCK_PRICING_SECTION)],
		},
		ignore_validate=True,
	)


# ----------------------------------------------------------------- permissions


def preserve_standard_docperms():
	"""Mirror standard DocPerms into Custom DocPerm before we add our own.

	The moment ANY Custom DocPerm row exists on a doctype, Frappe ignores that
	doctype's standard DocPerms entirely. Adding a Branch User row to Sales
	Invoice would therefore silently strip Accounts Manager, Sales User and
	everyone else. Mirroring first keeps them.
	"""
	doctypes = {p["parent"] for p in BRANCH_USER_PERMISSIONS}

	for doctype in sorted(doctypes):
		if not frappe.db.exists("DocType", doctype):
			continue
		# Only backfill a doctype that has no Custom DocPerm rows yet — if it has
		# any, a previous run (or an implementer) already owns the picture.
		if frappe.db.exists("Custom DocPerm", {"parent": doctype}):
			continue

		standard = frappe.get_all(
			"DocPerm",
			filters={"parent": doctype},
			fields=["role", "permlevel", *PERM_FIELDS],
		)
		for row in standard:
			_upsert_custom_docperm(doctype, row.role, row, permlevel=row.permlevel)


def setup_branch_user_permissions():
	"""Grant the Branch User role its document set."""
	for spec in BRANCH_USER_PERMISSIONS:
		doctype = spec["parent"]
		if not frappe.db.exists("DocType", doctype):
			continue
		_upsert_custom_docperm(doctype, BRANCH_USER_ROLE, spec)
		# A Branch Manager can reach everything a Branch User can. The difference
		# is cancelled visibility, which `branch_filters` applies, not DocPerm.
		_upsert_custom_docperm(doctype, BRANCH_MANAGER_ROLE, spec)


def _upsert_custom_docperm(doctype, role, spec, permlevel=0):
	"""Create or update one Custom DocPerm row."""
	if not role:
		return

	values = {f: int(spec.get(f) or 0) for f in PERM_FIELDS}

	existing = frappe.db.get_value(
		"Custom DocPerm", {"parent": doctype, "role": role, "permlevel": permlevel}, "name"
	)
	if existing:
		frappe.db.set_value("Custom DocPerm", existing, values, update_modified=False)
		return

	doc = frappe.new_doc("Custom DocPerm")
	doc.parent = doctype
	doc.parenttype = "DocType"
	doc.parentfield = "permissions"
	doc.role = role
	doc.permlevel = permlevel
	for field, value in values.items():
		setattr(doc, field, value)
	doc.insert(ignore_permissions=True)


# -------------------------------------------------------------- module profile


def ensure_module_profile():
	"""A Module Profile exposing only Yht Custom, so the sidebar is not a maze.

	Saving a Module Profile enqueues a background job to re-apply it to every
	user, and that leaves the document locked. A later ``after_migrate`` then
	dies with ``DocumentLockedError``. Two defences:

	1. Compare first and return without saving when nothing changed — which is
	   the normal case on every deploy after the first.
	2. When a save IS needed, clear a stale lock rather than fail the migrate.
	"""
	blocked = sorted(m for m in frappe.get_all("Module Def", pluck="name") if m != "Yht Custom")

	if frappe.db.exists("Module Profile", MODULE_PROFILE):
		current = sorted(
			frappe.get_all("Block Module", filters={"parent": MODULE_PROFILE}, pluck="module")
		)
		if current == blocked:
			return  # nothing to do — no save, no lock

		doc = frappe.get_doc("Module Profile", MODULE_PROFILE)
		if doc.is_locked:
			# The lock belongs to a finished job; holding the migrate hostage to it
			# achieves nothing.
			doc.unlock()
	else:
		doc = frappe.new_doc("Module Profile")
		doc.module_profile_name = MODULE_PROFILE

	doc.block_modules = []
	for module in blocked:
		doc.append("block_modules", {"module": module})
	doc.flags.ignore_permissions = True
	doc.save()


# --------------------------------------------------------- default print formats

#: Our formats become the default so a user pressing Print gets the right layout
#: without choosing. Sales Invoice is deliberately absent: ksa_compliance owns it
#: and its ZATCA Phase 2 format carries the QR code required for compliance.
#: Sales Invoice is deliberately ABSENT. ksa_compliance owns Sales Invoice
#: printing until ZATCA onboarding, and pinning a default here would override the
#: ZATCA format on a compliance document.
#:
#: Purchase Invoice is pinned to the GENERAL format, not the expense one. An
#: expense invoice is a subset of Purchase Invoice and default_print_format is
#: per-doctype, so one of the two has to be chosen manually; the general bill is
#: the far more common document, and the expense format stays one click away in
#: the print dialog.
DEFAULT_PRINT_FORMATS = {
	"Delivery Note": "YHT Delivery Note",
	"Quotation": "YHT Quotation",
	"Sales Order": "YHT Sales Order",
	"Purchase Invoice": "YHT Purchase Invoice",
	"Journal Entry": "YHT Journal Entry",
}


def setup_default_print_formats():
	for doctype, print_format in DEFAULT_PRINT_FORMATS.items():
		if not frappe.db.exists("Print Format", print_format):
			continue
		frappe.db.set_value("DocType", doctype, "default_print_format", print_format, update_modified=False)


# ---------------------------------------------------------------- report access

#: Reports the branch dashboard links to. The first three are this app's own
#: (yht_custom/report/) and ship their roles in their JSON; they are listed here
#: anyway so the Custom Role rule below covers them if anyone ever creates one,
#: and so they are re-pinned to inline execution after any manual promotion.
DASHBOARD_REPORTS = (
	"Stock Sales",
	"Collection",
	"Branch Receivables",
	"Customer Statement",
	"Item-wise Price List Rate",
	"Address Data Quality",
	"Stock Balance",
	"Stock Ledger",
	"Accounts Receivable Summary",
	"General Ledger",
)


def setup_report_roles():
	"""Give Branch User access to each dashboard report.

	🔴 The role must go on the **Custom Role**, not the Report's own `roles`.
	`frappe/core/doctype/report/report.py::is_permitted` does:

	    allowed = [Has Role rows for parent=<report>]
	    custom_roles = get_custom_allowed_roles("report", <report>)
	    if custom_roles:
	        allowed = custom_roles          # <-- REPLACES, does not merge

	All four of these reports already carry a Custom Role on this site (the legacy
	team created them), so adding to `Report.roles` is **silently ignored** — the
	report still refuses with "You don't have access to Report: …" while
	`Report.roles` shows the role present. That is exactly the trap this hit.

	Idempotent, and it never removes a role somebody else granted.
	"""
	for report in DASHBOARD_REPORTS:
		if not frappe.db.exists("Report", report):
			continue

		custom_role = frappe.db.get_value("Custom Role", {"report": report}, "name")

		if custom_role:
			doc = frappe.get_doc("Custom Role", custom_role)
		else:
			# No Custom Role yet: the Report's own roles are authoritative, so add
			# there instead of inventing a Custom Role that would then REPLACE them.
			if frappe.db.exists(
				"Has Role", {"parent": report, "parenttype": "Report", "role": BRANCH_USER_ROLE}
			):
				continue
			frappe.get_doc(
				{
					"doctype": "Has Role",
					"parent": report,
					"parenttype": "Report",
					"parentfield": "roles",
					"role": BRANCH_USER_ROLE,
				}
			).insert(ignore_permissions=True)
			continue

		if any(r.role == BRANCH_USER_ROLE for r in doc.roles):
			continue
		doc.append("roles", {"role": BRANCH_USER_ROLE})
		doc.flags.ignore_permissions = True
		doc.save()


# ------------------------------------------------------- branch payment modes


def setup_branch_payment_modes():
	"""Seed each Branch Configuration's tenderable Mode of Payment list.

	The child table has existed since Step 4 and was never populated — measured 0
	rows — so ``get_branch_payment_modes`` had nothing to filter on and the tender
	dialog would have had nothing to show.

	The seed is every mode that is BOTH enabled AND carries a default account for
	the branch's company. That pairing is not cosmetic: a mode without an account
	for the company cannot post, because ``get_bank_cash_account`` throws. On this
	site 21 modes are enabled and 8 are usable, so the unfiltered list would have
	offered 13 modes that fail at submit.

	Only ever ADDS. A row someone deleted by hand stays deleted, because the
	allowlist is a human decision about which tills a branch may touch and an
	after_migrate has no business overruling it.
	"""
	configs = frappe.get_all("Branch Configuration", fields=["name", "company"])
	if not configs:
		return

	for config in configs:
		company = config.company or frappe.defaults.get_global_default("company")
		if not company:
			continue

		existing = set(
			frappe.get_all(
				"Branch Configuration Mode of Payment",
				filters={"parent": config.name},
				pluck="mode_of_payment",
			)
		)
		if existing:
			# Configured already — leave the human's list alone.
			continue

		usable = frappe.db.get_all(
			"Mode of Payment Account",
			filters={"company": company, "default_account": ["!=", ""]},
			pluck="parent",
		)
		if not usable:
			continue

		enabled = frappe.get_all(
			"Mode of Payment",
			filters={"enabled": 1, "name": ["in", list(set(usable))]},
			fields=["name", "type"],
			order_by="type desc, name asc",
		)
		if not enabled:
			continue

		doc = frappe.get_doc("Branch Configuration", config.name)
		for mode in enabled:
			doc.append("mode_of_payment", {"mode_of_payment": mode.name})
		doc.save(ignore_permissions=True)


# ------------------------------------------------- repair: mirrored perm flags


def repair_mirrored_perm_flags():
	"""Restore `select` / `if_owner` the DocPerm mirror used to drop.

	``preserve_standard_docperms`` read both flags off the standard DocPerm and handed
	them to ``_upsert_custom_docperm``, which built its values dict from ``PERM_FIELDS``
	— a tuple that did not contain either. So both were read and discarded, and the
	mirrored Custom DocPerm came out more restrictive than the standard row it was
	supposed to preserve.

	Measured on this site before the fix: 5 rows — ``Address.if_owner`` (role All),
	``Customer Group`` and ``Territory`` ``select`` (role Customer), ``Item`` and
	``Item Group`` ``select`` (role Desk User). None of those roles has anything to do
	with branch scoping, which is what makes it worth healing rather than shrugging at.

	Only ever RAISES a flag the standard row already grants. It never clears one, so an
	implementer who deliberately widened a Custom DocPerm keeps their change.
	"""
	doctypes = sorted({p["parent"] for p in BRANCH_USER_PERMISSIONS})
	repaired = 0

	for doctype in doctypes:
		if not frappe.db.exists("DocType", doctype):
			continue

		standard = {
			(row.role, row.permlevel): row
			for row in frappe.get_all(
				"DocPerm",
				filters={"parent": doctype},
				fields=["role", "permlevel", "select", "if_owner"],
			)
		}
		if not standard:
			continue

		for row in frappe.get_all(
			"Custom DocPerm",
			filters={"parent": doctype},
			fields=["name", "role", "permlevel", "select", "if_owner"],
		):
			source = standard.get((row.role, row.permlevel))
			if not source:
				continue
			updates = {
				field: 1
				for field in ("select", "if_owner")
				if cint(source.get(field)) == 1 and cint(row.get(field)) == 0
			}
			if updates:
				frappe.db.set_value("Custom DocPerm", row.name, updates, update_modified=False)
				repaired += len(updates)

	if repaired:
		print(f"  yht_custom: restored {repaired} dropped select/if_owner flag(s)")
	return repaired


# ------------------------------------------------ dashboard reports run inline
#
# DASHBOARD_REPORTS is defined once, above, next to setup_report_roles. It used to
# be declared a second time here — a later redefinition of the same name, so the
# module-level constant the ROLE step read was silently this copy, and editing the
# first one changed nothing.


def run_dashboard_reports_inline():
	"""Stop the dashboard's reports being queued as Prepared Reports.

	Frappe PROMOTES a slow report to `prepared_report = 1` on its own, and once promoted the
	desk stops running it inline: it queues a background job and `frappe.query_report.data`
	stays empty until that job finishes. All four reports the branch dashboard links to had
	been promoted this way, so an operator clicking a tile got a queued job rather than a
	table — and the written guide promised them a table.

	Measured inline, as the branch user, over a one-month range:

	    Stock Balance                 1,741 rows   1,669 ms
	    Stock Ledger                      4 rows      81 ms
	    Accounts Receivable Summary      69 rows   1,119 ms
	    General Ledger                   36 rows   1,050 ms

	So the queueing bought nothing at the ranges anyone actually uses. Both flags are set:
	`prepared_report = 0` to run inline now, and `disable_prepared_report_automation = 1` so
	frappe does not silently promote them again the next time one runs slowly.

	The trade-off, stated: someone running Stock Ledger across three years (20,372 rows) now
	waits inline instead of getting a background job. That is the correct default for a branch
	operator looking at a month, and the guide already teaches setting the date range first.

	NOTE the field is `disable_prepared_report_automation`. There is no
	`disable_prepared_report` column in this version — querying that name raises
	`OperationalError: Unknown column`, and `bench execute` reports it as a bare
	`NameError: name 'yht_custom' is not defined`, because it wraps
	`frappe.get_attr(method)(*args)` in a bare `except Exception` and falls through to `eval`.
	Any runtime error in a function called that way is disguised as an import failure.
	"""
	meta = frappe.get_meta("Report")
	has_automation_flag = bool(meta.get_field("disable_prepared_report_automation"))

	changed = 0
	for name in DASHBOARD_REPORTS:
		if not frappe.db.exists("Report", name):
			continue

		updates = {}
		if cint(frappe.db.get_value("Report", name, "prepared_report")):
			updates["prepared_report"] = 0
		if has_automation_flag and not cint(
			frappe.db.get_value("Report", name, "disable_prepared_report_automation")
		):
			updates["disable_prepared_report_automation"] = 1

		if updates:
			# db.set_value, not doc.save(): Report is a standard doctype and saving one in a
			# non-developer-mode site raises "Cannot edit a standard report".
			frappe.db.set_value("Report", name, updates, update_modified=False)
			changed += len(updates)

	if changed:
		print(f"  yht_custom: {changed} prepared-report flag(s) cleared on dashboard reports")
	return changed
