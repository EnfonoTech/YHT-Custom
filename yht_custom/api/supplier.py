# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Create New Supplier — the dialog on Purchase Invoice / Order / Receipt.

The mirror of `api.customer`, ported from `rmax_custom.api.supplier`, with the
same four site-forced changes (mobile onto a Contact, no `ignore_permissions`,
no Branch kind, this site's field names) plus one of its own:

**A supplier's VAT number lives in the core `tax_id`.** There is no
`custom_vat_registration_number` on Supplier here, and there is no reason for
one: ZATCA makes its claims about the BUYER, so the duplicate rule on this side
is the client's own housekeeping rather than a compliance requirement. The B2B
address block is still enforced, because rmax enforces it and a supplier master
without an address is the same nuisance on either side of the ledger.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr

from yht_custom.api import party
from yht_custom.api.customer import (
    B2B_ADDRESS_REQUIRED,
    VAT_LENGTH,
    can_override_vat_duplicate,
    count_digits,
    is_b2b,
)


def _check_vat_shape(vat):
    if count_digits(vat) != VAT_LENGTH:
        frappe.throw(_("VAT Registration Number must be exactly {0} digits.").format(VAT_LENGTH))


def _check_vat_duplicate(vat, allow_duplicate, reason, exclude=None):
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

    filters = {"tax_id": vat}
    if exclude:
        filters["name"] = ["!=", exclude]
    clash = frappe.db.get_value("Supplier", filters, "name")
    if clash:
        frappe.throw(
            _("VAT Registration Number already used by Supplier: {0}. A Sales Manager can tick 'Allow Duplicate VAT' to override.").format(clash)
        )


def enforce_vat_duplicate_rule(doc, method=None):
    """`Supplier.validate`. The rules have to hold on the form too, not only the dialog."""
    vat = cstr(doc.get("tax_id")).strip()
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
def get_supplier_defaults():
    return {
        "supplier_group": party.default_group("Supplier"),
        "country": party._default_country(),
        "can_override_vat": can_override_vat_duplicate(),
        "can_create": bool(frappe.has_permission("Supplier", "create")),
        "vat_length": VAT_LENGTH,
    }


@frappe.whitelist()
def create_supplier_with_address(
    supplier_name: str,
    buyer_kind: str | None = None,
    supplier_type: str | None = None,
    supplier_group: str | None = None,
    mobile_no: str | None = None,
    email_id: str | None = None,
    tax_id: str | None = None,
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
    if not frappe.has_permission("Supplier", "create"):
        raise frappe.PermissionError(_("Not permitted to create a Supplier"))

    supplier_name = cstr(supplier_name).strip()
    if not supplier_name:
        frappe.throw(_("Supplier Name is required"))

    if frappe.db.exists("Supplier", {"supplier_name": supplier_name}):
        frappe.throw(_("Supplier {0} already exists").format(supplier_name))

    if count_digits(mobile_no) < 10:
        frappe.throw(_("Mobile number must have at least 10 digits."))

    b2b = is_b2b(buyer_kind, supplier_type)
    vat = cstr(tax_id).strip()

    if b2b:
        if not vat:
            frappe.throw(_("VAT Registration Number is required for B2B (Company) suppliers."))
        values = {
            "address_line1": address_line1,
            "custom_building_number": custom_building_number,
            "custom_area": custom_area,
            "city": city,
            "pincode": pincode,
        }
        for field, label in B2B_ADDRESS_REQUIRED:
            if not cstr(values.get(field)).strip():
                frappe.throw(_("{0} is required for B2B (Company) suppliers.").format(_(label)))

    if vat:
        _check_vat_shape(vat)
        _check_vat_duplicate(vat, allow_duplicate_vat, duplicate_vat_reason)

    doc = frappe.new_doc("Supplier")
    doc.supplier_name = supplier_name
    doc.supplier_type = "Company" if b2b else "Individual"
    doc.supplier_group = supplier_group or party.default_group("Supplier")

    if vat:
        doc.tax_id = vat
        if cint(allow_duplicate_vat):
            doc.custom_allow_duplicate_vat = 1
            doc.custom_duplicate_vat_reason = cstr(duplicate_vat_reason).strip()

    doc.insert()

    address_name = party._make_address(
        "Supplier",
        doc.name,
        supplier_name,
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
    contact_name = party._make_contact("Supplier", doc.name, supplier_name, mobile_no, email_id)

    return {
        "supplier": doc.name,
        "address": address_name,
        "contact": contact_name,
        "message": _("Supplier {0} created").format(doc.name),
    }


@frappe.whitelist()
def check_vat_available(vat: str, exclude: str | None = None):
    vat = cstr(vat).strip()
    if not vat:
        return {"taken_by": None}
    filters = {"tax_id": vat}
    if exclude:
        filters["name"] = ["!=", exclude]
    return {"taken_by": frappe.db.get_value("Supplier", filters, "name")}
