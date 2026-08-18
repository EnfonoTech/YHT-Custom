# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Idempotent provisioning, run on every ``after_migrate``.

Everything here must be safe to run repeatedly and must never clobber a manual
change an implementer made on the site.
"""

import frappe

from yht_custom.setup_branch_series import setup_branch_series

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
]

PERM_FIELDS = (
	"read", "write", "create", "submit", "cancel", "delete",
	"report", "export", "print", "email", "share", "amend",
)

BRANCH_USER_ROLE = "Branch User"
MODULE_PROFILE = "Branch User"


def after_migrate():
	"""Entry point wired from hooks.py."""
	ensure_branch_user_role()
	ensure_branch_custom_fields()
	preserve_standard_docperms()
	setup_branch_user_permissions()
	ensure_module_profile()
	setup_branch_series()
	frappe.db.commit()


# ------------------------------------------------------------------------ role


def ensure_branch_user_role():
	if frappe.db.exists("Role", BRANCH_USER_ROLE):
		return
	frappe.get_doc(
		{
			"doctype": "Role",
			"role_name": BRANCH_USER_ROLE,
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


def ensure_branch_custom_fields():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields({"Branch": BRANCH_CUSTOM_FIELDS}, ignore_validate=True)


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
			fields=["role", "permlevel", *PERM_FIELDS, "if_owner", "select", "amend"],
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
	"""A Module Profile exposing only Yht Custom, so the sidebar is not a maze."""
	all_modules = frappe.get_all("Module Def", pluck="name")
	blocked = [m for m in all_modules if m != "Yht Custom"]

	if frappe.db.exists("Module Profile", MODULE_PROFILE):
		doc = frappe.get_doc("Module Profile", MODULE_PROFILE)
	else:
		doc = frappe.new_doc("Module Profile")
		doc.module_profile_name = MODULE_PROFILE

	doc.block_modules = []
	for module in blocked:
		doc.append("block_modules", {"module": module})
	doc.flags.ignore_permissions = True
	doc.save()
