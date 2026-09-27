# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""CR-004 — collapse the print format list to one per doctype.

The client's complaint had two halves and only one of them was about mechanism:

* *"ഓരോന്നിനും ഓരോ പ്രിന്റ് ഫോർമാറ്റ് ആക്കേണ്ട… ടിക്ക് ഓപ്ഷൻ ആയിട്ട് കൊടുത്തിട്ട്"* —
  don't make a separate print format for each one, give it as a tick option.
* and the list is **"fully mixed"** — with every variant a record, picking a
  format from the dialog means reading past ten names to find the right one.

The tick options themselves were already delivered: Arabic follows the print
dialog's Language selector, the letterhead follows its Letter Head selector, and
the heading follows `Print As` / `select_print_heading`. What was left is the
list, and that is what this module does — it RETIRES the records those options
made redundant.

## What is disabled, and why each one is safe

Measured on 2026-09-27, the `KATC *` variants are not different layouts:

    KATC Sales Order No LH      html IDENTICAL to KATC Sales Order
    KATC Sales Order Arabic     same include + `katc_show_arabic`, now set by language
    KATC Quotation Arabic       same include + `katc_show_arabic`, now set by language
    KATC Quotation No LH        a 6,506-character HAND COPY of the layout, which is
                                exactly the drift hazard the shim design removed
    KATC Quotation Proforma     routed to by `KATC Quotation`
    KATC Proforma Invoice       routed to by `KATC Sales Order`

🔴 DISABLED, NEVER DELETED. `disabled = 1` hides a format from the picker and is
one column to reverse; a delete is not, and a format someone saved as their
personal default would take their print with it. The non-KATC leftovers are
disabled for the same reason and by name, never by a pattern — `ZATCA Phase 1`,
`ZATCA Phase 2` and `KATHOOM KHOBAR INV FORMAT NEW` are all deliberate and stay.

⚠️ AND ONLY WHERE THE SWITCH IS ON. This changes which formats an operator can
pick, on a bench that also serves the client's live site.
"""

import frappe

from yht_custom import features

#: Format → the format that now covers it. The value is documentation; nothing
#: reads it. Named individually because a pattern like `KATC % Arabic` would one
#: day match something nobody meant.
SUPERSEDED = {
	"KATC Quotation Arabic": "KATC Quotation, with the dialog's Language set to Arabic",
	"KATC Quotation No LH": "KATC Quotation, with No Letterhead ticked or the Print Without LH button",
	"KATC Quotation Proforma": "KATC Quotation, with Print As = Proforma Invoice",
	"KATC Sales Order Arabic": "KATC Sales Order, with the dialog's Language set to Arabic",
	"KATC Sales Order No LH": "KATC Sales Order, with No Letterhead ticked or the Print Without LH button",
	"KATC Proforma Invoice": "KATC Sales Order, with Print As = Proforma Invoice",
}

#: Formats from before this project that make the list "fully mixed". Disabled so
#: the picker shows one obvious answer per doctype.
#:
#: ⚠️ `KATHOOM KHOBAR INV FORMAT NEW` is NOT here. It is the byte-faithful
#: reproduction of the incumbent's invoice and is deliberate. Neither are the two
#: ZATCA formats, which are the compliance app's.
LEGACY_NOISE = ("YHT Quotation", "YHT Sales Order", "YHT Delivery Note", "Sales Order PD v2")

#: doctype → the one format its print dialog should open on.
DEFAULTS = {
	"Quotation": "KATC Quotation",
	"Sales Order": "KATC Sales Order",
	"Sales Invoice": "KATC Tax Invoice",
	"Delivery Note": "KATC Delivery Note",
	"Purchase Order": "KATC Purchase Order",
}


def setup_print_consolidation() -> dict:
	"""Idempotent. Behind `cr_004_print_heading`."""
	if not features.enabled("cr_004_print_heading"):
		return {"skipped": "cr_004_print_heading is off for this site"}

	from yht_custom.form_layout import _set_property

	disabled = []
	for name in list(SUPERSEDED) + list(LEGACY_NOISE):
		if not frappe.db.exists("Print Format", name):
			continue
		if frappe.db.get_value("Print Format", name, "disabled"):
			continue
		frappe.db.set_value("Print Format", name, "disabled", 1, update_modified=False)
		disabled.append(name)

	defaults = {}
	for doctype, fmt in DEFAULTS.items():
		if not frappe.db.exists("Print Format", fmt):
			continue
		if frappe.db.get_value("Print Format", fmt, "disabled"):
			# Never point a doctype at a format nobody can pick.
			frappe.log_error(
				message="%s is disabled; not setting it as %s's default" % (fmt, doctype),
				title="yht_custom: print consolidation",
			)
			continue
		_set_property(doctype, None, "default_print_format", fmt, "Data", for_doctype=True)
		defaults[doctype] = fmt

	return {"disabled": disabled, "defaults": defaults, "live": live_formats()}


def live_formats() -> dict:
	"""What the picker offers per doctype. The number the client was complaining about."""
	out = {}
	for doctype in DEFAULTS:
		out[doctype] = sorted(
			frappe.get_all("Print Format", filters={"doc_type": doctype, "disabled": 0}, pluck="name")
		)
	return out


def report() -> dict:
	"""``bench --site … execute yht_custom.print_consolidation.report``"""
	summary = {"live": live_formats(), "superseded": sorted(SUPERSEDED)}
	print(frappe.as_json(summary, indent=1))
	return summary
