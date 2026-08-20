# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Address Data Quality — the ZATCA worklist, one row per address to fix.

`saudi_address.national_address_gaps` counts the problem. Counting it does not fix
it, and the client cannot fix what they cannot see per-customer. This is the list:
who to call, which address, what is missing.

WHY IT MATTERS, from ksa_compliance's own mapping — `buyer_district` comes off
`custom_area` and `buyer_building_number` off `custom_building_number`, and both
are REQUIRED for a Standard (B2B) e-invoice. Measured on this site: 578 of 578
Saudi addresses have no district and 535 no building number. Every one of those is
an invoice ZATCA will reject once Phase 2 is live.

The companion `export_worklist()` writes the same rows as a CSV with the `ID`
column first, so the client fills in the blanks and uploads it back through
Data Import → Update Existing Records. No retyping, no re-keying customer names.
"""

import csv
import os
import re

import frappe
from frappe import _
from frappe.utils import cint, cstr, get_site_path

from yht_custom.saudi_address import BUILDING_NUMBER, CHECKS, SAUDI

#: A street name that is nothing but digits is not a street name. Measured: 366 of
#: 578 Saudi addresses on this site have a purely numeric `address_line1`, which is
#: what ksa_compliance maps to ZATCA's `street_name`. The legacy import put the
#: BUILDING NUMBER in the street field — so the building number the client thinks
#: they do not have is very often already sitting there.
NUMERIC_ONLY = re.compile(r"^[\d\s\-]+$")

#: Fields the client has to supply, in the order the form asks for them.
REQUIRED_FOR_ZATCA = (
	("address_line1", "Street"),
	("custom_building_number", "Building No"),
	("custom_area", "District"),
	("city", "City"),
	("pincode", "Postal Code"),
)

#: Columns in the re-uploadable CSV. `ID` must come first for Data Import.
EXPORT_COLUMNS = (
	"ID",
	"Address Title",
	"Address Line 1",
	"Building Number",
	"Area/District",
	"City/Town",
	"Postal Code",
	"Short Address",
)

EXPORT_FIELDS = (
	"name",
	"address_title",
	"address_line1",
	"custom_building_number",
	"custom_area",
	"city",
	"pincode",
	"custom_short_address",
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return _columns(), _rows(filters)


def _rows(filters):
	party_type = filters.get("party_type")
	rows = []

	for address in _addresses(party_type):
		missing = [
			label for field, label in REQUIRED_FOR_ZATCA if not cstr(address.get(field)).strip()
		]
		malformed = [
			(frappe.get_meta("Address").get_label(field) or field)
			for field, pattern, _shape in CHECKS
			if cstr(address.get(field)).strip() and not pattern.match(cstr(address.get(field)).strip())
		]

		if cint(filters.get("only_problems", 1)) and not missing and not malformed:
			continue
		if filters.get("blocks_zatca") and not _blocks_zatca(missing):
			continue

		street = cstr(address.get("address_line1")).strip()
		numeric_street = bool(street) and bool(NUMERIC_ONLY.match(street))
		if numeric_street:
			malformed.append(_("Street is a number"))

		rows.append(
			{
				"suggested_building_number": (
					street
					if numeric_street
					and BUILDING_NUMBER.match(street)
					and not cstr(address.get("custom_building_number")).strip()
					else ""
				),
				"party_type": address.get("party_type"),
				"party": address.get("party"),
				"party_name": address.get("party_name"),
				"address": address.get("name"),
				"blocks_zatca": 1 if _blocks_zatca(missing) else 0,
				"missing": ", ".join(missing),
				"malformed": ", ".join(malformed),
				"address_line1": address.get("address_line1"),
				"custom_building_number": address.get("custom_building_number"),
				"custom_area": address.get("custom_area"),
				"city": address.get("city"),
				"pincode": address.get("pincode"),
				"custom_short_address": address.get("custom_short_address"),
			}
		)

	rows.sort(key=lambda r: (-r["blocks_zatca"], cstr(r["party_name"])))
	return rows


def _blocks_zatca(missing):
	"""District and building number are the two ZATCA rejects outright."""
	return "District" in missing or "Building No" in missing


def _addresses(party_type=None):
	"""Every Saudi address, ONCE, with the party or parties it belongs to.

	A Dynamic Link join rather than one query per address: 579 addresses would
	otherwise be 579 round trips. But the join multiplies — an address linked to
	both a Customer and a Supplier came back twice, which turned 578 Saudi
	addresses into 583 worklist rows and would have made Data Import process the
	same ID twice. Links are collapsed per address instead.
	"""
	rows = frappe.db.sql(
		"""SELECT a.name, a.address_title, a.country, a.address_line1, a.city, a.pincode,
		          a.custom_building_number, a.custom_area, a.custom_short_address
		   FROM `tabAddress` a ORDER BY a.name""",
		as_dict=True,
	)

	links = {}
	for link in frappe.db.sql(
		"""SELECT parent, link_doctype, link_name FROM `tabDynamic Link`
		   WHERE parenttype = 'Address' AND link_doctype IN ('Customer', 'Supplier')""",
		as_dict=True,
	):
		links.setdefault(link.parent, []).append(link)

	names = {}
	for doctype in ("Customer", "Supplier"):
		field = "customer_name" if doctype == "Customer" else "supplier_name"
		names[doctype] = {
			row.name: row.get(field) for row in frappe.get_all(doctype, fields=["name", field])
		}

	out = []
	for row in rows:
		if SAUDI not in cstr(row.country).lower():
			continue

		owners = links.get(row.name) or []
		if party_type:
			owners = [o for o in owners if o.link_doctype == party_type]
			if not owners:
				continue

		first = owners[0] if owners else None
		row.party_type = first.link_doctype if first else None
		row.party = first.link_name if first else None
		row.party_name = " / ".join(
			cstr(names.get(o.link_doctype, {}).get(o.link_name) or o.link_name) for o in owners
		) or cstr(row.address_title)
		out.append(row)
	return out



def _columns():
	return [
		{"fieldname": "blocks_zatca", "label": _("Blocks ZATCA"), "fieldtype": "Check", "width": 100},
		{"fieldname": "party_type", "label": _("Party Type"), "fieldtype": "Data", "width": 90},
		{
			"fieldname": "party",
			"label": _("Party"),
			"fieldtype": "Dynamic Link",
			"options": "party_type",
			"width": 120,
		},
		{"fieldname": "party_name", "label": _("Name"), "fieldtype": "Data", "width": 230},
		{
			"fieldname": "address",
			"label": _("Address"),
			"fieldtype": "Link",
			"options": "Address",
			"width": 190,
		},
		{"fieldname": "missing", "label": _("Missing"), "fieldtype": "Data", "width": 220},
		{"fieldname": "malformed", "label": _("Malformed"), "fieldtype": "Data", "width": 150},
		{"fieldname": "custom_building_number", "label": _("Building No"), "fieldtype": "Data", "width": 100},
		{
			"fieldname": "suggested_building_number",
			"label": _("Suggested Building No"),
			"fieldtype": "Data",
			"width": 150,
		},
		{"fieldname": "custom_area", "label": _("District"), "fieldtype": "Data", "width": 150},
		{"fieldname": "city", "label": _("City"), "fieldtype": "Data", "width": 120},
		{"fieldname": "pincode", "label": _("Postal Code"), "fieldtype": "Data", "width": 100},
		{"fieldname": "address_line1", "label": _("Street"), "fieldtype": "Data", "width": 200},
		{"fieldname": "custom_short_address", "label": _("Short Address"), "fieldtype": "Data", "width": 120},
	]


# ------------------------------------------------------------------- CSV export


def export_worklist(only_problems: int = 1) -> str:
	"""Write the fixable rows as a Data-Import-ready CSV.

	    bench --site … execute \\
	      yht_custom.yht_custom.report.address_data_quality.address_data_quality.export_worklist

	Upload the filled file through **Data Import → Address → Update Existing
	Records**. The `ID` column is what makes it an update rather than 578 new
	addresses, so it is written first and never omitted.

	The CSV carries ONLY real Address fields, so it stays import-safe. The
	`Suggested Building No` the report shows is deliberately NOT pre-filled here:
	it is a guess derived from a numeric street field, and a guess written straight
	into a statutory field that nobody reviewed is worse than a blank one. The
	report is where a human decides; this file is only the upload vehicle.
	"""
	rows = _rows(frappe._dict(only_problems=cint(only_problems)))
	folder = get_site_path("private", "files")
	os.makedirs(folder, exist_ok=True)
	path = os.path.join(folder, "address-worklist.csv")

	with open(path, "w", newline="") as handle:
		writer = csv.writer(handle)
		writer.writerow(EXPORT_COLUMNS)
		for row in rows:
			address = frappe.db.get_value(
				"Address", row["address"], EXPORT_FIELDS, as_dict=True
			)
			writer.writerow([cstr(address.get(field)) for field in EXPORT_FIELDS])

	print(f"  {len(rows)} address(es) -> {path}")
	return path
