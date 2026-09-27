# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""CR-004 — collapse the print format list to one KATC format per doctype.

The client's complaint had two halves and only one was about mechanism:

* *"ഓരോന്നിനും ഓരോ പ്രിന്റ് ഫോർമാറ്റ് ആക്കേണ്ട… ടിക്ക് ഓപ്ഷൻ ആയിട്ട് കൊടുത്തിട്ട്"* —
  don't make a separate print format for each one, give it as a tick option.
* and the list is **"fully mixed"** — with every variant its own record, picking a
  format means reading past ten names to find the right one.

The tick options were already delivered: Arabic follows the print dialog's
Language selector, the letterhead follows its Letter Head selector, and the
heading follows `Print As` / `select_print_heading`. What was left is the list,
and this module retires the records those options made redundant.

## What is disabled, and why each one is safe

Measured 2026-09-27 — the `KATC *` variants are not different layouts:

    KATC Sales Order No LH      html IDENTICAL to KATC Sales Order
    KATC Sales Order Arabic     same include + `katc_show_arabic`, now set by language
    KATC Quotation Arabic       same include + `katc_show_arabic`, now set by language
    KATC Quotation No LH        a 6,506-character HAND COPY, which is the drift the
                                shim design removed — and it still puts the
                                letterhead in a `<thead>` (gotcha 105)
    KATC Quotation Proforma     routed to by KATC Quotation
    KATC Proforma Invoice       routed to by KATC Sales Order

Each was A/B'd against the format that replaces it: seven of the eight printed
documents reproduce byte-for-byte once frappe's page chrome is excluded. The
eighth is `KATC Quotation No LH`, whose differences are listed above.

🔴 DISABLED, NEVER DELETED. `disabled = 1` hides a format from the picker and is
one column to reverse; a delete is not, and would take the print of anyone who
saved it as a personal default.
"""

import frappe

from yht_custom import features

#: Format → what now covers it. The value is documentation; nothing reads it.
#: Named individually, never by a pattern like `KATC % Arabic`, which would one
#: day match something nobody meant.
SUPERSEDED = {
	"KATC Quotation Arabic": "KATC Quotation, with the dialog's Language set to Arabic",
	"KATC Quotation No LH": "KATC Quotation, with No Letterhead ticked or the Print Without LH button",
	"KATC Quotation Proforma": "KATC Quotation, with Print As = Proforma Invoice",
	"KATC Sales Order Arabic": "KATC Sales Order, with the dialog's Language set to Arabic",
	"KATC Sales Order No LH": "KATC Sales Order, with No Letterhead ticked or the Print Without LH button",
	"KATC Proforma Invoice": "KATC Sales Order, with Print As = Proforma Invoice",
}

#: 🔴 EMPTY, AND THAT IS A CORRECTION RATHER THAN AN OVERSIGHT.
#:
#: This held `YHT Quotation`, `YHT Sales Order`, `YHT Delivery Note`,
#: `Sales Order PD v2`, `Drop Shipping Format` and `Point of Sale`, disabled on the
#: premise that they were pre-project leftovers making the list mixed. The premise
#: was wrong and `test_the_six_incumbent_formats_are_untouched` — a guard written
#: for exactly this — caught it:
#:
#: * the `YHT *` formats are **this app's own**, module `Yht Custom`
#: * `setup.DEFAULT_PRINT_FORMATS` sets them as each doctype's
#:   `default_print_format` on EVERY migrate
#:
#: Disabling them left those doctypes defaulting to a format nobody could pick.
#: Only the KATC variants above — which this project created, and which its own
#: tick options made redundant — are retired here.
#:
#: ⚠️ WHAT THAT LEAVES, STATED RATHER THAN QUIETLY FIXED: Quotation, Sales Order
#: and Delivery Note each still offer TWO formats — the KATC one the buttons use
#: and the YHT one the doctype defaults to. Which is authoritative is the client's
#: decision, not something to settle by disabling the other.
LEGACY_NOISE = ()

#: The doctypes this module reports on. It does NOT set their defaults.
#:
#: 🔴 `setup.DEFAULT_PRINT_FORMATS` ALREADY OWNS `default_print_format`. An earlier
#: version of this module wrote a Property Setter for the same setting, so two
#: mechanisms drove one value and the Property Setter silently won.
#:
#: 🔴 AND SALES INVOICE MUST HAVE NO DEFAULT AT ALL —
#: `test_sales_invoice_has_no_pinned_default` states why: ksa_compliance owns Sales
#: Invoice printing until ZATCA onboarding. That test reads the DocType row, so the
#: Property Setter changed the effective default WITHOUT failing it. The check and
#: the change were looking at different places, which is the whole lesson.
DOCTYPES = ("Quotation", "Sales Order", "Sales Invoice", "Delivery Note", "Purchase Order")


def setup_print_consolidation() -> dict:
	"""Idempotent. Behind `cr_004_print_heading`."""
	if not features.enabled("cr_004_print_heading"):
		return {"skipped": "cr_004_print_heading is off for this site"}

	disabled = []
	for name in list(SUPERSEDED) + list(LEGACY_NOISE):
		if not frappe.db.exists("Print Format", name):
			continue
		if frappe.db.get_value("Print Format", name, "disabled"):
			continue
		frappe.db.set_value("Print Format", name, "disabled", 1, update_modified=False)
		disabled.append(name)

	return {"disabled": disabled, "live": live_formats()}


def restore(names=None) -> dict:
	"""Put a retired format back in the picker.

	    bench --site … execute yht_custom.print_consolidation.restore

	Exists because "disabled, never deleted" is only a real promise if turning one
	back on is a documented single step rather than a database edit.
	"""
	names = names or list(SUPERSEDED)
	back = []
	for name in names:
		if frappe.db.exists("Print Format", name) and frappe.db.get_value("Print Format", name, "disabled"):
			frappe.db.set_value("Print Format", name, "disabled", 0, update_modified=False)
			back.append(name)
	frappe.db.commit()
	print(frappe.as_json({"restored": back}, indent=1))
	return {"restored": back}


def live_formats() -> dict:
	"""What the picker offers per doctype — the number the client complained about."""
	return {
		doctype: sorted(
			frappe.get_all("Print Format", filters={"doc_type": doctype, "disabled": 0}, pluck="name")
		)
		for doctype in DOCTYPES
	}


def report() -> dict:
	"""``bench --site … execute yht_custom.print_consolidation.report``"""
	summary = {"live": live_formats(), "superseded": sorted(SUPERSEDED)}
	print(frappe.as_json(summary, indent=1))
	return summary


def drop_stale_default_print_format_setters() -> dict:
	"""Delete the `default_print_format` Property Setters an earlier version wrote.

	🔴 A PROPERTY SETTER IS A ROW, NOT A LINE OF CODE. Removing the code that
	wrote these leaves them working. And they do not merely duplicate
	`setup.DEFAULT_PRINT_FORMATS` — they OVERRIDE it, because `frappe.get_meta`
	applies Property Setters over the DocType row.

	Measured on `yht-test` 2026-09-27, after the code was already reverted:

	    tabDocType.default_print_format      Sales Invoice -> NULL   (looks correct)
	    Property Setter                      Sales Invoice -> KATC Tax Invoice

	So Sales Invoice was pinned to a non-ZATCA format while every check that read
	the DocType row — including
	`test_sales_invoice_has_no_pinned_default` — reported it clean.
	`ksa_compliance` owns Sales Invoice printing until ZATCA onboarding; this puts
	that back.

	Scoped to the five doctypes this module ever touched, never to the property in
	general: another app is entitled to set its own default.
	"""
	deleted = []
	for row in frappe.get_all(
		"Property Setter",
		filters={"property": "default_print_format", "doc_type": ["in", list(DOCTYPES)]},
		fields=["name", "doc_type", "value"],
	):
		frappe.delete_doc("Property Setter", row.name, force=1, ignore_permissions=True)
		deleted.append("%s -> %s" % (row.doc_type, row.value))

	for doctype in DOCTYPES:
		frappe.clear_cache(doctype=doctype)
	frappe.db.commit()

	effective = {d: frappe.get_meta(d).default_print_format or None for d in DOCTYPES}
	summary = {"deleted": deleted, "effective_default_now": effective}
	print(frappe.as_json(summary, indent=1))
	return summary
