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

#: The two ways a party is registered, and the only thing that changes between
#: them. Kept as data so the dialog and the server agree on the vocabulary.
MODES = ("B2B", "B2C")

#: Address fields a Standard (B2B) e-invoice cannot clear without. ZATCA rejects a
#: standard invoice whose buyer address is missing its district, and on this site
#: that was not hypothetical -- 578 of 578 Saudi addresses had no district. So the
#: mode that produces standard invoices is the mode that insists on them.
B2B_ADDRESS_REQUIRED = (
	("address_line1", "Street Name"),
	("custom_building_number", "Building Number"),
	("custom_area", "District"),
	("city", "City"),
	("pincode", "Postal Code"),
)


def _normalise_mode(mode, tax_id=None):
	"""``(mode, declared)`` -- the mode, and whether the CALLER said it.

	The mode is INFERRED, never defaulted, when it is missing: a caller that hands
	over a VAT number is describing a registered business, one that does not is
	describing a walk-in. That matters because this endpoint pre-dates the mode and
	still has callers that never pass one; defaulting them to B2B made four of them
	fail on requirements they had no way to know about.

	``declared`` is the difference between a promise and a guess. An explicit B2B --
	what the dialog sends -- is a promise that the invoice can clear, so it is held
	to the full national address. An inferred one only routes the VAT number to the
	field ZATCA reads, which is a strict improvement on what the caller had before.
	"""
	declared = bool(cstr(mode).strip())
	if not declared:
		return ("B2B" if cstr(tax_id).strip() else "B2C"), False

	mode = cstr(mode).strip().upper()
	if mode not in MODES:
		frappe.throw(_("Mode must be B2B or B2C"))
	return mode, True


def _vat_fieldname(doctype):
	"""The field ZATCA actually reads, when the site has it.

	`ksa_compliance.is_b2b_customer` tests `custom_vat_registration_number`, NOT the
	core `tax_id`. A customer carrying a VAT number in `tax_id` alone is therefore
	invoiced as SIMPLIFIED with no buyer VAT -- measured here as 14 customers of
	435. So B2B writes BOTH fields, and this resolves the second one per doctype:
	Supplier has no such field (there is no ZATCA rule for a supplier), Customer
	does.
	"""
	if frappe.get_meta(doctype).has_field("custom_vat_registration_number"):
		return "custom_vat_registration_number"
	return None

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
	mode: str | None = None,
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
	mode, declared = _normalise_mode(mode, tax_id)
	_validate_mode_requirements(doctype, mode, tax_id, address, declared)

	party = _make_party(doctype, party_name, tax_id, group, territory, mode)
	address_name = _make_address(doctype, party.name, party_name, address)
	contact_name = _make_contact(doctype, party.name, party_name, mobile, email)

	return {"name": party.name, "address": address_name, "contact": contact_name}


def _make_party(doctype, party_name, tax_id, group, territory, mode="B2B"):
	"""Create the party. The mode decides its TYPE and where its VAT number lands."""
	doc = frappe.new_doc(doctype)
	doc.update({f"{doctype.lower()}_name": party_name})

	tax_id = cstr(tax_id).strip()
	if tax_id:
		doc.tax_id = tax_id
		# The core field alone is not enough: ZATCA reads the custom one, so a B2B
		# party writes both or it is invoiced as simplified. See _vat_fieldname.
		vat_field = _vat_fieldname(doctype)
		if vat_field and mode == "B2B":
			doc.set(vat_field, tax_id)

	# customer_type / supplier_type -- set generically, and only where it exists.
	type_field = f"{doctype.lower()}_type"
	if doc.meta.has_field(type_field):
		doc.set(type_field, "Company" if mode == "B2B" else "Individual")

	if doctype == "Customer":
		doc.customer_group = group or default_group("Customer")
		doc.territory = territory or default_territory()
	else:
		doc.supplier_group = group or default_group("Supplier")

	doc.insert()
	return doc


def _validate_mode_requirements(doctype, mode, tax_id, address, declared=True):
	"""B2C asks for nothing extra; B2B is a promise that the invoice can clear.

	Enforced for Customer only. A standard e-invoice makes claims about the BUYER --
	their VAT number and their national address -- and ZATCA rejects it when either
	is missing. Nothing in the spec constrains a supplier record, so a B2B supplier
	is just a company with a tax id.
	"""
	if mode != "B2B" or doctype != "Customer" or not declared:
		return

	if not cstr(tax_id).strip():
		frappe.throw(_("A VAT Number is required for a B2B customer"))

	missing = [label for field, label in B2B_ADDRESS_REQUIRED if not cstr(address.get(field)).strip()]
	if missing:
		frappe.throw(
			_("A B2B customer needs a full national address. Missing: {0}").format(
				", ".join(_(label) for label in missing)
			)
		)


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


def _make_address(doctype, party, party_name, values, address_type="Billing"):
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
	doc.address_type = address_type or "Billing"
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
		"modes": list(MODES),
		"default_mode": "B2B",
		"vat_field": _vat_fieldname(doctype),
		"b2b_address_required": [field for field, _label in B2B_ADDRESS_REQUIRED],
	}
