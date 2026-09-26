# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""CR-002 — the district ZATCA reads, recovered from the field the client typed it in.

## The CR's premise was backwards, and the code says so

CR-002 asks to "remap district to `county`". That would break the e-invoice.
`ksa_compliance` decides which fieldname ZATCA reads, and it is hardcoded
upstream in `sales_invoice_additional_fields._set_buyer_address`:

    buyer_district <- custom_area

`custom_area` is not ours to choose. It is also, independently, where the
client's OWN tooling puts the district — the ad-hoc `Address Fetching` client
script (ported to `public/js/address.js`, CR-001) splits a pasted SPL national
address and assigns `parts[3]` to `custom_area`. So both the regulator's reader
and the client's writer already agree on `custom_area`.

`county` is the LEGACY field. Measured on `yht-khobhar` 2026-09-26, 630
addresses:

    city            630
    county          340      <- legacy import, dirty
    custom_area      19      <- typed since the SPL script landed 2026-09-25

So the job is not a remap. It is a RECOVERY: read the 340 legacy values, work out
which of them are genuinely districts, and copy those into `custom_area`.

## Why this cannot be a blind copy

A sample of the 340 (top 40 by frequency) contains four different kinds of value:

    genuine district   ASH SHAMALIYAH · AL MALAZ · QURTUBAH · AL OLAYA · AL THOQBA
    the city again     Dammam · RIYADH · JEDDAH · AL KHOBAR · ALKHOBAR
    city + district    ALKHOBAR ASH SHAMALIYAH · AL KHUBAR ASH SHAMALIYAH
    not a district     PRINCE TALAL STREET · the literal string "NULL" (3 rows)

Copying the lot would put "Dammam" in the district cell of a Dammam invoice and
"NULL" on three others. `classify()` sorts each value into one of five buckets
and only the `district` bucket is ever written. Everything else is REPORTED, not
guessed — the ambiguous ones are a data-cleanup job for the client, and this
module's whole output is a worklist for them.

🔴 AN EXISTING `custom_area` IS NEVER OVERWRITTEN. Those 19 rows were typed by a
human through the SPL flow; a derived value from a legacy column does not get to
win against one. `backfill()` only fills blanks.
"""

import re

import frappe
from frappe.utils import cstr

#: Values that are noise in any column. Compared after squashing.
JUNK = {"NULL", "NA", "N A", "NONE", "-", "0"}

#: A value carrying one of these is a street or a landmark, not a district.
NOT_A_DISTRICT = ("STREET", "ROAD", "HIGHWAY", "P O BOX", "POBOX", "BUILDING")

#: Trailing noise that decorates a real district: "Al Olaya Dist", "AL MALAZ DIST.".
DISTRICT_SUFFIX = re.compile(r"\b(DIST|DIST\.|DISTRICT)\s*$", re.I)

#: Spelling variants of the same city, squashed. The client's data carries
#: ALKHOBAR, AL KHOBAR, AL KHUBAR and AL KHOBER for one city, and the city-only
#: test below is worthless unless they all collapse to one string.
CITY_ALIASES = (("KHUBAR", "KHOBAR"), ("KHOBER", "KHOBAR"), ("ALKOBAR", "ALKHOBAR"))

BUCKETS = ("district", "city_only", "street", "junk", "empty")


def _squash(value: str) -> str:
	"""Upper-case, alphanumerics only — for COMPARING, never for storing."""
	squashed = re.sub(r"[^A-Z0-9]", "", cstr(value).upper())
	for wrong, right in CITY_ALIASES:
		squashed = squashed.replace(wrong, right)
	return squashed


def _tidy(value: str) -> str:
	"""Collapse whitespace and drop a trailing "Dist" — the value we would store."""
	tidied = re.sub(r"\s+", " ", cstr(value).replace(",", " ")).strip(" ,.-")
	tidied = DISTRICT_SUFFIX.sub("", tidied).strip(" ,.-")
	return tidied


def _drop_prefix(original: str, prefix_len: int) -> str:
	"""`original` minus its first `prefix_len` ALPHANUMERIC characters.

	Walks the original so the surviving text keeps its own spacing and case:
	squashing is only ever a comparison device, and a district stored as
	"ASHSHAMALIYAH" would be a new data-quality problem in place of the old one.
	"""
	seen = 0
	for index, char in enumerate(original):
		if seen >= prefix_len:
			return original[index:].strip(" ,.-")
		if char.isalnum():
			seen += 1
	return ""


def classify(county: str, city: str) -> tuple:
	"""``(bucket, value)`` for one legacy `county` reading, against its own `city`.

	`value` is what would be stored, and is `""` for every bucket but `district`.

	The city is passed in per row rather than matched against a list of Saudi
	cities, deliberately: "Dammam" is a district name somewhere and a city name on
	a Dammam address, and only the row itself can tell those apart.
	"""
	tidied = _tidy(county)
	squashed = _squash(tidied)
	if not squashed:
		return "empty", ""
	if squashed in {_squash(j) for j in JUNK}:
		return "junk", ""

	upper = tidied.upper()
	if any(marker in upper for marker in NOT_A_DISTRICT):
		return "street", ""

	city_squashed = _squash(city)
	if city_squashed:
		if squashed == city_squashed:
			return "city_only", ""
		if squashed.startswith(city_squashed):
			# "ALKHOBAR ASH SHAMALIYAH" — the city, then the district after it.
			remainder = _drop_prefix(tidied, len(city_squashed))
			if _squash(remainder):
				return "district", remainder
			return "city_only", ""

	return "district", tidied


def _rows():
	return frappe.get_all(
		"Address",
		fields=["name", "county", "city", "custom_area", "country"],
		filters={"county": ["is", "set"]},
	)


def survey() -> dict:
	"""Count the buckets without writing anything.

	    bench --site … execute yht_custom.address_district.survey
	"""
	counts = {bucket: 0 for bucket in BUCKETS}
	counts["already_set"] = 0
	examples = {bucket: [] for bucket in BUCKETS}

	for row in _rows():
		if cstr(row.custom_area).strip():
			counts["already_set"] += 1
			continue
		bucket, value = classify(row.county, row.city)
		counts[bucket] += 1
		if len(examples[bucket]) < 8:
			examples[bucket].append({"address": row.name, "county": row.county, "city": row.city, "district": value})

	summary = {"with_county": len(_rows()), "counts": counts, "examples": examples}
	print(frappe.as_json(summary, indent=1))
	return summary


def backfill(commit: bool = False) -> dict:
	"""Copy every confidently-classified district into the blank `custom_area`.

	Dry by default. `commit=True` writes, and writes with `db.set_value` +
	`update_modified=False`: an Address is linked from submitted invoices, and
	bumping `modified` on 300 of them would make every open form stale for a
	change the operator did not make.

	    bench --site … execute yht_custom.address_district.backfill --kwargs "{'commit': True}"
	"""
	written = 0
	skipped = {bucket: 0 for bucket in BUCKETS}

	for row in _rows():
		if cstr(row.custom_area).strip():
			continue
		bucket, value = classify(row.county, row.city)
		if bucket != "district" or not value:
			skipped[bucket] += 1
			continue
		if commit:
			frappe.db.set_value("Address", row.name, "custom_area", value, update_modified=False)
		written += 1

	if commit:
		frappe.db.commit()

	summary = {"committed": bool(commit), "filled": written, "left_for_the_client": skipped}
	print(frappe.as_json(summary, indent=1))
	return summary
