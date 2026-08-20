# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Simple Customer and Supplier creation (plan 5.10).

ERPNext's own Customer form carries ~40 fields across six sections, and a branch
operator setting up a walk-in needs six of them. The quick-entry dialog frappe
offers is not enough either: it creates the party and stops, so the address —
which is where every ZATCA field lives — has to be added afterwards through a
second form that operators skip. On this site that is not hypothetical: 578 of
578 Saudi addresses have no district, and every Standard e-invoice needs one.

So this endpoint creates the party, its address and its contact in ONE call, and
the address it creates is a Saudi national address (see `saudi_address`).

Party creation is a real write from the browser, so every guard is here rather
than in the dialog:

* `frappe.has_permission(doctype, "create")` — a Branch User holds create on
  Customer and NOT on Supplier, and that difference must be enforced server-side.
* No `ignore_permissions` anywhere. If the role cannot make the record, the call
  fails; it does not quietly succeed with elevated rights.
* One transaction. A party with a half-written address is worse than no party.
"""

import frappe
from frappe import _
from frappe.utils import cstr

SUPPORTED = ("Customer", "Supplier")

#: Address fields the dialog collects, in the order they are asked for.
ADDRESS_FIELDS = (
	"address_line1",
	"address_line2",
	"custom_building_number",
	"custom_area",
	"custom_additional_number",
	"custom_unit_number",
	"custom_short_address",
	"city",
	"pincode",
	"country",
)


@frappe.whitelist()
def create_party(
	doctype: str,
	party_name: str,
	tax_id: str | None = None,
	group: str | None = None,
	territory: str | None = None,
	mobile: str | None = None,
	email: str | None = None,
	address: dict | str | None = None,
):
	"""Create a Customer or Supplier with its address and contact in one go.

	Returns ``{"name": ..., "address": ..., "contact": ...}``.
	"""
	doctype = cstr(doctype).strip()
	if doctype not in SUPPORTED:
		frappe.throw(_("Unsupported party type"))

	# Every @frappe.whitelist() is a public HTTP endpoint. This is the boundary.
	if not frappe.has_permission(doctype, "create"):
		raise frappe.PermissionError(_("Not permitted to create a {0}").format(_(doctype)))

	party_name = cstr(party_name).strip()
	if not party_name:
		frappe.throw(_("Name is required"))

	address = frappe.parse_json(address) if isinstance(address, str) else (address or {})

	party = _make_party(doctype, party_name, tax_id, group, territory)
	address_name = _make_address(doctype, party.name, party_name, address)
	contact_name = _make_contact(doctype, party.name, party_name, mobile, email)

	return {"name": party.name, "address": address_name, "contact": contact_name}


def _make_party(doctype, party_name, tax_id, group, territory):
	doc = frappe.new_doc(doctype)
	doc.update({f"{doctype.lower()}_name": party_name})

	if tax_id:
		doc.tax_id = cstr(tax_id).strip()

	if doctype == "Customer":
		doc.customer_type = "Company"
		doc.customer_group = group or default_group("Customer")
		doc.territory = territory or default_territory()
	else:
		doc.supplier_group = group or default_group("Supplier")

	doc.insert()
	return doc


def default_group(doctype: str) -> str | None:
	"""A NON-GROUP party group, resolved in order of trustworthiness.

	`Selling Settings.customer_group` on this site is `All Customer Groups` — a
	group node — and `Customer.validate_customer_group` throws on one: "Cannot
	select a Group type Customer Group." So the configured setting cannot be
	trusted, and ERPNext's own quick entry fails the same way. `Buying Settings
	.supplier_group` is simply empty.

	Falling back to the most-used value on existing records is the honest answer to
	"what does this client actually use": 427 of 428 customers are `Commercial`.
	"""
	group_doctype = f"{doctype} Group"
	field = f"{doctype.lower()}_group"
	setting = "Selling Settings" if doctype == "Customer" else "Buying Settings"

	configured = frappe.db.get_single_value(setting, field)
	if configured and not frappe.db.get_value(group_doctype, configured, "is_group"):
		return configured

	leaves = frappe.get_all(group_doctype, filters={"is_group": 0}, pluck="name")
	if not leaves:
		return None

	most_used = frappe.db.get_all(
		doctype,
		filters={field: ["in", leaves]},
		fields=[field, "count(name) as total"],
		group_by=field,
		order_by="total desc",
		limit=1,
	)
	if most_used:
		return most_used[0].get(field)

	return leaves[0]


def default_territory() -> str | None:
	configured = frappe.db.get_single_value("Selling Settings", "territory")
	if configured and not frappe.db.get_value("Territory", configured, "is_group"):
		return configured
	leaves = frappe.get_all("Territory", filters={"is_group": 0}, pluck="name")
	return leaves[0] if leaves else None


def _make_address(doctype, party, party_name, values):
	"""Skip silently when nothing was filled in — an empty address is not an error.

	`saudi_address.before_insert` turns a Short Code into the address title, and
	`saudi_address.validate` checks the national-address formats. Neither is
	bypassed here.
	"""
	filled = {field: cstr(values.get(field)).strip() for field in ADDRESS_FIELDS}
	if not filled.get("address_line1") and not filled.get("city"):
		return None

	doc = frappe.new_doc("Address")
	doc.update(filled)
	doc.address_title = party_name
	doc.address_type = "Billing"
	doc.country = filled.get("country") or _default_country()
	doc.is_primary_address = 1
	doc.append("links", {"link_doctype": doctype, "link_name": party})
	doc.insert()
	return doc.name


def _make_contact(doctype, party, party_name, mobile, email):
	mobile = cstr(mobile).strip()
	email = cstr(email).strip()
	if not mobile and not email:
		return None

	doc = frappe.new_doc("Contact")
	doc.first_name = party_name
	doc.append("links", {"link_doctype": doctype, "link_name": party})
	if mobile:
		doc.append("phone_nos", {"phone": mobile, "is_primary_mobile_no": 1})
	if email:
		doc.append("email_ids", {"email_id": email, "is_primary": 1})
	doc.insert()
	return doc.name


def _default_country():
	company = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")
	return (
		(company and frappe.db.get_value("Company", company, "country"))
		or frappe.db.get_single_value("System Settings", "country")
		or "Saudi Arabia"
	)


@frappe.whitelist()
def get_party_defaults(doctype: str):
	"""Groups and territories the dialog offers, filtered to what the role may read."""
	doctype = cstr(doctype).strip()
	if doctype not in SUPPORTED:
		frappe.throw(_("Unsupported party type"))

	return {
		"group": default_group(doctype),
		"territory": default_territory() if doctype == "Customer" else None,
		"country": _default_country(),
		"can_create": bool(frappe.has_permission(doctype, "create")),
	}
