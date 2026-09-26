# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""CR-014 — the Company's Unified/National Number.

Saudi Arabia's "الرقم الموحد" — a ten-digit identifier beginning with 7, issued
alongside the Commercial Registration and now widely asked for on documents.

🔴 NO FIELD HELD IT. Measured on `yht-khobhar` 2026-09-26, `Company` carried six
Custom Fields — four HR/payroll accounts, a tab break and a section break — and
none of them was this. The CR's own open question ("does a Unified Number field
already exist on Company") is therefore answered: no, and this creates it.

⚠️ THE NUMBER ITSELF IS THE CLIENT'S TO SUPPLY, AND THE DESIGN MAKES THAT SAFE.
`katc_letterhead.build_content` renders the Unified No. segment only when the
field is filled, so the letterhead is byte-for-byte unchanged until someone types
it in — no placeholder, no "7XXXXXXXXX", nothing that could be mistaken for a
real registration on a document that goes to a customer or to ZATCA. Once it is
typed, the next `bench migrate` (or a direct call to
`katc_letterhead.setup_katc_letterhead`) rewrites the letterhead and both
languages pick it up.

The validation is deliberately shaped like `saudi_address.validate`: it only
judges a value being entered or changed, so a Company saved for any other reason
never fails on a field nobody has filled yet.
"""

import re

import frappe
from frappe import _
from frappe.utils import cstr

FIELDNAME = "custom_unified_number"

#: Ten digits, the first of which is 7.
PATTERN = re.compile(r"^7\d{9}$")

CUSTOM_FIELDS = [
	{
		"fieldname": FIELDNAME,
		"label": "Unified Number",
		"fieldtype": "Data",
		"insert_after": "tax_id",
		"length": 10,
		"description": "الرقم الموحد — ten digits starting with 7. Printed on the letterhead when filled.",
	}
]


def validate(doc, method=None):
	"""`Company.validate` — shape only, and only what is being touched."""
	value = cstr(doc.get(FIELDNAME)).strip()
	if not value:
		return

	doc.set(FIELDNAME, value)

	if not doc.is_new() and not doc.has_value_changed(FIELDNAME):
		return

	if not PATTERN.match(value):
		frappe.throw(
			_("{0} must be ten digits starting with 7. Got {1}.").format(
				frappe.bold(_("Unified Number")), frappe.bold(value)
			),
			title=_("Invalid Unified Number"),
		)


def setup_unified_number() -> dict:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields({"Company": CUSTOM_FIELDS}, ignore_validate=True)
	return {"field": FIELDNAME, "filled": bool(_current())}


def _current() -> str:
	company = frappe.db.get_value("Company", {}, "name")
	if not company or not frappe.db.has_column("Company", FIELDNAME):
		return ""
	return cstr(frappe.db.get_value("Company", company, FIELDNAME)).strip()
