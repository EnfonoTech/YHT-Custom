# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Create New Customer — the dialog the operator gets on Sales Invoice / Quotation.

Ported from `rmax_custom.api.customer` so the fleet behaves the same way. Four
things could not be copied verbatim, each because of this site rather than
preference:

* **The mobile number goes onto a Contact.** `Customer.mobile_no` and `email_id`
  are READ ONLY here — ERPNext derives them from the primary Contact. RMAX writes
  them straight onto the Customer; doing that here would look like it worked and
  persist nothing.
* **The Arabic name field is `custom_customer_name_arabic`**, the one
  `arabic_translation` ships, not RMAX's `custom_customer_name_ar`. This site
  already carries Arabic customer data in the first; adding the second would be a
  second source of truth for the same fact.
* **There is no `Branch` customer type.** `customer_type` offers Company /
  Individual / Partnership, so the Branch exemption RMAX carries is dropped
  rather than throwing on save.
* **No `ignore_permissions`.** RMAX inserts with permissions bypassed. Every
  `@frappe.whitelist()` is a public HTTP endpoint, so a role that cannot create a
  Customer does not get to create one through this door either.

The VAT rules are RMAX's and are the point of the exercise: exactly 15 digits, no
duplicate unless a manager says so in writing, and a B2B customer that cannot
clear a standard e-invoice is refused at the door.
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, cstr

from yht_custom.api import party

#: Roles trusted to sign off a duplicate VAT registration number.
VAT_DUPLICATE_OVERRIDE_ROLES = ("Sales Manager", "Sales Master Manager", "System Manager")

#: A Saudi VAT registration number is exactly this many digits.
VAT_LENGTH = 15

#: ZATCA rejects a standard invoice whose buyer address is missing any of these.
B2B_ADDRESS_REQUIRED = (
    ("address_line1", "Address Line 1"),
    ("custom_building_number", "Building Number"),
    ("custom_area", "Area/District"),
    ("city", "City/Town"),
    ("pincode", "Postal Code"),
)


def count_digits(value) -> int:
    return len(re.sub(r"\D", "", cstr(value)))


def can_override_vat_duplicate(user=None) -> bool:
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    return bool(set(frappe.get_roles(user)) & set(VAT_DUPLICATE_OVERRIDE_ROLES))


def is_b2b(buyer_kind, customer_type=None) -> bool:
    """B2B when the dialog says so, or when an older caller only sent a type."""
    kind = cstr(buyer_kind).strip().upper()
    if kind:
        return kind.startswith("B2B")
    return customer_type == "Company"


def _check_vat_shape(vat):
    if count_digits(vat) != VAT_LENGTH:
        frappe.throw(_("VAT Registration Number must be exactly {0} digits.").format(VAT_LENGTH))


def _check_vat_duplicate(vat, allow_duplicate, reason, exclude=None):
    """Refuse a repeated VAT number unless a manager signs for it.

    Enforced here rather than only in the dialog: the dialog pre-checks so the
    operator gets the message before typing an address, but this endpoint is
    reachable over HTTP and the check that matters is the one on the server.
    """
    if not vat:
        return

    if cint(allow_duplicate):
        if not can_override_vat_duplicate():
            frappe.throw(
                _("You do not have permission to override the VAT duplicate check. Required role: Sales Manager.")
            )
        if not cstr(reason).strip():
            frappe.throw(_("Duplicate VAT Reason is required when overriding the VAT duplicate check."))
        return

    filters = {"custom_vat_registration_number": vat}
    if exclude:
        filters["name"] = ["!=", exclude]
    clash = frappe.db.get_value("Customer", filters, "name")
    if clash:
        frappe.throw(
            _("VAT Registration Number already used by Customer: {0}. A Sales Manager can tick 'Allow Duplicate VAT' to override.").format(clash)
        )


def enforce_vat_duplicate_rule(doc, method=None):
    """`Customer.validate`. The same rules when someone edits the form directly.

    Without this the dialog is the only place the rules hold, and the Customer
    form itself becomes the way around them.
    """
    vat = cstr(doc.get("custom_vat_registration_number")).strip()
    if not vat:
        return

    _check_vat_shape(vat)
    _check_vat_duplicate(
        vat,
        doc.get("custom_allow_duplicate_vat"),
        doc.get("custom_duplicate_vat_reason"),
        exclude=doc.name,
    )


@frappe.whitelist()
def get_customer_defaults():
    """What the dialog needs before it can draw itself."""
    return {
        "customer_group": party.default_group("Customer"),
        "territory": party.default_territory(),
        "country": party._default_country(),
        "can_override_vat": can_override_vat_duplicate(),
        "can_create": bool(frappe.has_permission("Customer", "create")),
        "vat_length": VAT_LENGTH,
    }


@frappe.whitelist()
def create_customer_with_address(
    customer_name: str,
    buyer_kind: str | None = None,
    customer_type: str | None = None,
    customer_group: str | None = None,
    mobile_no: str | None = None,
    email_id: str | None = None,
    custom_customer_name_arabic: str | None = None,
    custom_vat_registration_number: str | None = None,
    allow_duplicate_vat=0,
    duplicate_vat_reason: str | None = None,
    address_type: str | None = None,
    address_line1: str | None = None,
    address_line2: str | None = None,
    custom_building_number: str | None = None,
    custom_area: str | None = None,
    custom_short_address: str | None = None,
    custom_additional_number: str | None = None,
    city: str | None = None,
    pincode: str | None = None,
    country: str | None = None,
):
    """Create the Customer, its Address and its Contact in one call."""
    if not frappe.has_permission("Customer", "create"):
        raise frappe.PermissionError(_("Not permitted to create a Customer"))

    customer_name = cstr(customer_name).strip()
    if not customer_name:
        frappe.throw(_("Customer Name is required"))

    if frappe.db.exists("Customer", {"customer_name": customer_name}):
        frappe.throw(_("Customer {0} already exists").format(customer_name))

    if count_digits(mobile_no) < 10:
        frappe.throw(_("Mobile number must have at least 10 digits."))

    b2b = is_b2b(buyer_kind, customer_type)
    vat = cstr(custom_vat_registration_number).strip()

    if b2b:
        if not vat:
            frappe.throw(_("VAT Registration Number is required for B2B (Company) customers."))
        values = {
            "address_line1": address_line1,
            "custom_building_number": custom_building_number,
            "custom_area": custom_area,
            "city": city,
            "pincode": pincode,
        }
        for field, label in B2B_ADDRESS_REQUIRED:
            if not cstr(values.get(field)).strip():
                frappe.throw(_("{0} is required for B2B (Company) customers.").format(_(label)))

    if vat:
        _check_vat_shape(vat)
        _check_vat_duplicate(vat, allow_duplicate_vat, duplicate_vat_reason)

    doc = frappe.new_doc("Customer")
    doc.customer_name = customer_name
    doc.customer_type = "Company" if b2b else "Individual"
    doc.customer_group = customer_group or party.default_group("Customer")
    doc.territory = party.default_territory()

    if vat:
        # tax_id too: ksa_compliance reads the custom field, the rest of erpnext
        # reads tax_id, and a customer carrying only one of them reads as B2C
        # somewhere. See yht_custom.api.party._vat_fieldname.
        doc.custom_vat_registration_number = vat
        doc.tax_id = vat
        if cint(allow_duplicate_vat):
            doc.custom_allow_duplicate_vat = 1
            doc.custom_duplicate_vat_reason = cstr(duplicate_vat_reason).strip()

    if custom_customer_name_arabic and doc.meta.has_field("custom_customer_name_arabic"):
        doc.custom_customer_name_arabic = cstr(custom_customer_name_arabic).strip()

    doc.insert()

    address_name = party._make_address(
        "Customer",
        doc.name,
        customer_name,
        {
            "address_line1": address_line1,
            "address_line2": address_line2,
            "custom_building_number": custom_building_number,
            "custom_area": custom_area,
            "custom_short_address": custom_short_address,
            "custom_additional_number": custom_additional_number,
            "city": city,
            "pincode": pincode,
            "country": country,
        },
        address_type=address_type or "Billing",
    )

    # mobile_no / email_id are read-only on Customer — the Contact is where they live.
    contact_name = party._make_contact("Customer", doc.name, customer_name, mobile_no, email_id)

    if address_name:
        doc.db_set("customer_primary_address", address_name, update_modified=False)

    return {
        "customer": doc.name,
        "address": address_name,
        "contact": contact_name,
        "message": _("Customer {0} created").format(doc.name),
    }


@frappe.whitelist()
def check_vat_available(vat: str, exclude: str | None = None):
    """Does this VAT number already belong to someone? Asked by the dialog."""
    vat = cstr(vat).strip()
    if not vat:
        return {"taken_by": None}
    filters = {"custom_vat_registration_number": vat}
    if exclude:
        filters["name"] = ["!=", exclude]
    return {"taken_by": frappe.db.get_value("Customer", filters, "name")}
