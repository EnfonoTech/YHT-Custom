# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Saudi national address, with the Short Code as the address title (plan 5.9).

WHAT ALREADY EXISTED. `ksa_compliance` ships two of the fields — and, crucially,
it decides which fieldnames ZATCA reads. From its own
`sales_invoice_additional_fields._set_buyer_address`:

    buyer_street_name            <- address_line1
    buyer_additional_street_name <- address_line2
    buyer_building_number        <- custom_building_number
    buyer_city                   <- city
    buyer_district               <- custom_area
    buyer_additional_number      <- 'not available for now'   # hardcoded upstream

So `address_line1` IS the ZATCA street name and `custom_area` IS the district.
Inventing parallel fields would have produced a form that looks correct and an
e-invoice that carries nothing. The three fields added here are the ones
`ksa_compliance` does NOT provide.

⚠️ `buyer_additional_number` is a hardcoded placeholder string upstream, so the
Additional Number captured here does NOT currently reach the ZATCA XML. It is
still worth capturing — it is part of the national address, the client asked for
it, and the upstream stub is a bug that will be fixed. Re-check this at ZATCA
onboarding.

DATA QUALITY, measured on the live site before writing any validation:

    579 addresses, 577 Saudi Arabia
    579 of 579 have NO district        <- every ZATCA standard invoice would fail
    536 of 579 have NO building number
     51 malformed pincodes ("00", "3463231", "325478")

That last number is why validation only fires on a value being entered or
changed. A blanket throw would have made 51 existing customers unsaveable for
reasons that predate this app, which turns a data-quality problem into an outage.
"""

import re

import frappe
from frappe import _
from frappe.utils import cstr

#: Matched loosely on purpose: this site carries a Country record literally named
#: "Saudi Arabia -المملكة العربية السعودية" alongside the normal one.
SAUDI = "saudi"

BUILDING_NUMBER = re.compile(r"^\d{4}$")
ADDITIONAL_NUMBER = re.compile(r"^\d{4}$")
POSTAL_CODE = re.compile(r"^\d{5}$")
#: SPL short address: four letters then four digits, e.g. RQAA2929.
SHORT_ADDRESS = re.compile(r"^[A-Z]{4}\d{4}$")

#: The three national-address fields ksa_compliance does not ship.
#:
#: ⚠️ THE `insert_after` VALUES HERE ARE THE ADDRESS LAYOUT (client sheet item
#: 29), NOT DECORATION. `create_custom_fields` re-applies every key on this dict
#: — `insert_after` included — on every migrate, so this is the only place these
#: three can be positioned; a second opinion elsewhere would be overwritten and
#: then rewritten, forever. The standard fields around them are ordered by
#: `field_layout.FIELD_MOVES["Address"]` and the other apps' custom fields by
#: `field_layout.CUSTOM_FIELD_MOVES["Address"]`; the left column reads
#: Short Address · Type · Building No · Street Name · Additional No · Unit No ·
#: District · Postal Code · City · Country.
ADDRESS_CUSTOM_FIELDS = [
	{
		"fieldname": "custom_additional_number",
		"label": "Additional Number",
		"fieldtype": "Data",
		"insert_after": "address_line1",
		"length": 4,
		"description": "Four-digit secondary number from the national address.",
	},
	{
		"fieldname": "custom_unit_number",
		"label": "Unit Number",
		"fieldtype": "Data",
		"insert_after": "custom_additional_number",
		"length": 8,
	},
	{
		# First on the form, in place of the hidden Address Title it feeds.
		"fieldname": "custom_short_address",
		"label": "Short Address",
		"fieldtype": "Data",
		"insert_after": "address_title",
		"length": 8,
		"description": "SPL short code, four letters then four digits (e.g. <code>RQAA2929</code>). Becomes the address title on a new address.",
	},
]

#: (fieldname, pattern, human-readable shape) for every checked field.
CHECKS = (
	("custom_building_number", BUILDING_NUMBER, "4 digits"),
	("custom_additional_number", ADDITIONAL_NUMBER, "4 digits"),
	("pincode", POSTAL_CODE, "5 digits"),
	("custom_short_address", SHORT_ADDRESS, "4 letters then 4 digits"),
)


def is_saudi(doc) -> bool:
	return SAUDI in cstr(doc.get("country")).lower()


def validate(doc, method=None):
	"""Normalise and check the national-address fields. Registered on `validate`."""
	if doc.get("custom_short_address"):
		doc.custom_short_address = cstr(doc.custom_short_address).strip().upper()

	if not is_saudi(doc):
		return

	for fieldname, pattern, shape in CHECKS:
		value = cstr(doc.get(fieldname)).strip()
		if not value:
			# Deliberately not required here. Presence is ZATCA's business, and it
			# already throws at invoice time; blocking an address save would only
			# stop someone fixing the rest of the record.
			continue

		# Only judge what the user is actually touching. 51 addresses already carry
		# a malformed pincode from the legacy import — those stay saveable until
		# somebody edits that field.
		if not doc.is_new() and not doc.has_value_changed(fieldname):
			continue

		if not pattern.match(value):
			label = doc.meta.get_label(fieldname) or fieldname
			frappe.throw(
				_("{0} must be {1}. Got {2}.").format(frappe.bold(_(label)), shape, frappe.bold(value)),
				title=_("Invalid national address"),
			)


def before_insert(doc, method=None):
	"""Short Code becomes the address title, per the client sheet.

	Only on insert. `Address.autoname` builds the document name from the title, so
	rewriting the title of an existing address would leave the name and the title
	disagreeing for no gain — the name cannot change.
	"""
	short_code = cstr(doc.get("custom_short_address")).strip().upper()
	if short_code:
		doc.address_title = short_code


# ------------------------------------------------------------------ reporting


def national_address_gaps(company: str | None = None) -> dict:
	"""Count what ZATCA will reject. Run before onboarding, not after.

	    bench --site … execute yht_custom.saudi_address.national_address_gaps

	Every figure here is a standard-invoice blocker: `buyer_district` and
	`buyer_building_number` are required for a Standard (B2B) e-invoice, and both
	come off the Address.
	"""
	rows = frappe.get_all(
		"Address",
		fields=[
			"name",
			"country",
			"pincode",
			"city",
			"address_line1",
			"custom_building_number",
			"custom_area",
			"custom_short_address",
		],
	)
	saudi = [row for row in rows if SAUDI in cstr(row.country).lower()]

	def missing(field):
		return sum(1 for row in saudi if not cstr(row.get(field)).strip())

	malformed = {}
	for fieldname, pattern, _shape in CHECKS:
		malformed[fieldname] = sum(
			1
			for row in saudi
			if cstr(row.get(fieldname)).strip() and not pattern.match(cstr(row.get(fieldname)).strip())
		)

	summary = {
		"addresses": len(rows),
		"saudi": len(saudi),
		"missing_street": missing("address_line1"),
		"missing_city": missing("city"),
		"missing_district": missing("custom_area"),
		"missing_building_number": missing("custom_building_number"),
		"missing_postal_code": missing("pincode"),
		"missing_short_code": missing("custom_short_address"),
		"malformed": malformed,
	}
	print(frappe.as_json(summary, indent=1))
	return summary
