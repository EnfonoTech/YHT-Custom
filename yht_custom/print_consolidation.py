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
#:   `default_print_format` on EVERY migrate (Sales Order excepted since
#:   2026-10-10 — row 12 needs the printer icon to reach the KATC router)
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

#: 2026-10-11 — THE CLIENT'S OWN ANSWER to "which print formats are canonical?"
#: Osaid Kamal (YHT's coordinator): "please make sure the print formats are the
#: following in the live version". They are site-built formats (`standard = No`),
#: created by `saheed@kathoomcompany.com` directly on `yht-khobhar` on 2026-10-03/06
#: — they exist only in that site's database — and each is that doctype's default
#: through a `default_print_format` Property Setter. Nothing here WRITES them; the
#: constant is what `check_client_defaults` verifies, and what the cleanup below
#: must never undo.
CLIENT_DEFAULT_PRINT_FORMATS = {
	"Sales Invoice": "SALES-INVOICE",
	"Quotation": "SALES-QUOTATION",
	"Purchase Order": "PURCHASE-ORDER",
	"Delivery Note": "DELIVERY-NOTE W/O HEAD",
}

#: Other client-built formats `check_client_defaults` accepts for a doctype. Row 35
#: (2026-10-11): live Delivery Note defaults to `DELIVERY-NOTE W HEAD` (a Property Setter by
#: `saheed@`, 2026-10-12) while Osaid's list says `DELIVERY-NOTE W/O HEAD`, which does not
#: exist there — so the check read SKIP ("no such format") over a default that IS a client
#: format. Which of the two is final is the client's question, not decided here, which is why
#: `CLIENT_DEFAULT_PRINT_FORMATS` itself is left as Osaid wrote it.
CLIENT_DEFAULT_ALTERNATIVES = {
	"Delivery Note": ("DELIVERY-NOTE W HEAD",),
}


def setup_print_consolidation() -> dict:
	"""Idempotent. Behind `cr_004_print_heading`."""
	if not features.enabled("cr_004_print_heading"):
		return {"skipped": "cr_004_print_heading is off for this site"}

	disabled = []
	for name in list(SUPERSEDED) + list(LEGACY_NOISE):
		current = frappe.db.get_value("Print Format", name, ["disabled", "standard"], as_dict=True)
		if not current:
			continue
		# Row 35: a format the client built (`standard != Yes`) is never touched, even if it
		# happens to carry a retired name.
		if current.standard != "Yes":
			continue
		if current.disabled:
			continue
		frappe.db.set_value("Print Format", name, "disabled", 1, update_modified=False)
		disabled.append(name)

	# 🔴 A DEFAULT THAT POINTS AT A FORMAT THIS STEP JUST RETIRED MAKES THE PRINTER ICON
	# THROW ("Print Format … is disabled"). On the live site `yaser@` pinned Sales Order
	# to `KATC Proforma Invoice` on 2026-09-24, which is in SUPERSEDED. Only setters
	# that are stale NOW go — a named user's choice of an enabled format stays.
	dropped = _delete_setters(classify_default_print_format_setters()["delete"])
	for doctype in DOCTYPES:
		frappe.clear_cache(doctype=doctype)

	return {"disabled": disabled, "stale_defaults_dropped": dropped, "live": live_formats()}


def restore(names=None) -> dict:
	"""Put a retired format back in the picker.

	    bench --site … execute yht_custom.print_consolidation.restore

	Exists because "disabled, never deleted" is only a real promise if turning one
	back on is a documented single step rather than a database edit.
	"""
	names = names or list(SUPERSEDED)
	back = []
	for name in names:
		current = frappe.db.get_value("Print Format", name, ["disabled", "standard"], as_dict=True)
		# Row 35: never re-enable a format the client built (`standard != Yes`).
		if current and current.standard == "Yes" and current.disabled:
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


def classify_default_print_format_setters() -> dict:
	"""Read-only. Which `default_print_format` setters on the five doctypes are
	stale, and which are somebody's choice.

	🔴 THE FIRST VERSION OF THIS CLEANUP SWEPT BY (doctype, property) AND DELETED
	THE CLIENT'S OWN DEFAULTS. It was written on 2026-09-27 for one incident — an
	earlier version of this module pinned Sales Invoice to `KATC Tax Invoice` with a
	Property Setter, which overrides the DocType row and put a non-ZATCA format in
	front of a tax invoice. Nobody else set these then. Since 2026-09-24 the client
	has set five of their own on the live site, and on 2026-10-11 Osaid asked for
	four of them in writing. `backfill_meeting_0923_data` calls this and had not yet
	run on live: the next migrate there would have undone the request without a word.

	What is deleted, and why each is safe:

	* the target Print Format does not exist, or is disabled — a default nobody can
	  use; the printer icon would throw
	* `modified_by` is Administrator AND the target is one of this app's own formats
	  (`standard = Yes`) — what the original incident looked like: provisioning code
	  pinning a doctype to a format it ships
	* a blank value saved by Administrator — meaningless, and the DocType row already
	  says what the default is

	What is KEPT: a setter whose target is a format the client built (`standard =
	No`), whoever saved it — this includes the ones a script saved on their behalf —
	and a setter a named user chose, while its target is enabled. A blank value a
	named user saved is theirs too: it means "no default" on purpose.
	"""
	delete, keep = [], []
	for row in frappe.get_all(
		"Property Setter",
		filters={"property": "default_print_format", "doc_type": ["in", list(DOCTYPES)]},
		fields=["name", "doc_type", "value", "modified_by"],
	):
		named_user = row.modified_by not in ("Administrator", None, "")
		entry = (row.name, row.doc_type, row.value)
		if not row.value:
			if named_user:
				keep.append(entry + ("a default cleared on purpose by %s" % row.modified_by,))
			else:
				delete.append(entry + ("blank, saved by provisioning code",))
			continue
		target = frappe.db.get_value("Print Format", row.value, ["disabled", "standard"], as_dict=True)
		if not target:
			delete.append(entry + ("points at a Print Format that does not exist",))
		elif target.disabled:
			delete.append(entry + ("points at a disabled Print Format",))
		elif target.standard != "Yes":
			keep.append(entry + ("a format the client built",))
		elif named_user:
			keep.append(entry + ("chosen by %s" % row.modified_by,))
		else:
			delete.append(entry + ("pinned to one of this app's own formats by provisioning code",))
	return {"delete": delete, "keep": keep}


def _delete_setters(entries) -> list:
	"""Delete the setters `classify_default_print_format_setters` marked. No commit."""
	deleted = []
	for name, doctype, value, why in entries:
		frappe.delete_doc("Property Setter", name, force=1, ignore_permissions=True)
		deleted.append("%s -> %s (%s)" % (doctype, value, why))
	return deleted


def drop_stale_default_print_format_setters() -> dict:
	"""Delete the stale `default_print_format` setters — and ONLY those.

	    bench --site … execute yht_custom.print_consolidation.drop_stale_default_print_format_setters

	See `classify_default_print_format_setters` for the rule and for why it is not
	a sweep. A Property Setter is a row, not a line of code: removing the code that
	wrote one leaves it working, and `frappe.get_meta` applies it OVER the DocType
	row that `setup.DEFAULT_PRINT_FORMATS` owns.
	"""
	plan = classify_default_print_format_setters()
	deleted = _delete_setters(plan["delete"])

	for doctype in DOCTYPES:
		frappe.clear_cache(doctype=doctype)
	frappe.db.commit()

	effective = {d: frappe.get_meta(d).default_print_format or None for d in DOCTYPES}
	summary = {
		"deleted": deleted,
		"kept": ["%s -> %s (%s)" % (doctype, value, why) for _name, doctype, value, why in plan["keep"]],
		"effective_default_now": effective,
	}
	print(frappe.as_json(summary, indent=1))
	return summary


def _is_client_built(name, doctype) -> bool:
	"""An enabled Print Format for `doctype` that is the client's own (`standard != Yes`)."""
	if not name:
		return False
	info = frappe.db.get_value("Print Format", name, ["doc_type", "standard", "disabled"], as_dict=True)
	return bool(info) and info.doc_type == doctype and info.standard != "Yes" and not info.disabled


def check_client_defaults() -> dict:
	"""Does each doctype default to the format the client asked for?

	    bench --site … execute yht_custom.print_consolidation.check_client_defaults

	Run it after ANY migrate on a site that carries the client's formats. Three
	outcomes, never folded together: OK, FAIL, and SKIP for a site that has no such
	format (`yht-test` until the client's formats are copied there) — a check that
	cannot run must not read as a pass.
	"""
	rows = {}
	for doctype, fmt in CLIENT_DEFAULT_PRINT_FORMATS.items():
		accepted = (fmt, *CLIENT_DEFAULT_ALTERNATIVES.get(doctype, ()))
		effective = frappe.get_meta(doctype).default_print_format
		current = (
			frappe.db.get_value("Print Format", effective, "disabled", as_dict=True) if effective else None
		)
		if effective and (current is None or current.disabled):
			# A default nobody can print with: the printer icon throws.
			reason = (
				"the default names a Print Format that does not exist"
				if current is None
				else "the default Print Format is disabled"
			)
			rows[doctype] = {"expected": fmt, "effective": effective, "status": "FAIL", "reason": reason}
		elif not any(frappe.db.exists("Print Format", name) for name in accepted):
			rows[doctype] = {
				"expected": fmt,
				"effective": effective,
				"status": "SKIP - this site has no such format",
				"reason": "none of %s exists on this site" % ", ".join(accepted),
			}
		elif effective in accepted:
			rows[doctype] = {"expected": fmt, "effective": effective, "status": "OK", "reason": ""}
		elif _is_client_built(effective, doctype):
			# 🔴 The client is building the whole set of formats himself (Osaid, 2026-10-14: "we just
			# need them editable even after being set as default"), so the default will keep moving
			# between names we have never heard of. What this check guards is OUR code re-pointing a
			# default; a default on an enabled format the CLIENT built (`standard = No`, same
			# doctype) is their choice, not a regression. A format that is ours, missing or disabled
			# still fails above and below.
			rows[doctype] = {
				"expected": fmt,
				"effective": effective,
				"status": "OK",
				"reason": "client-built format (their own choice)",
			}
		else:
			rows[doctype] = {
				"expected": fmt,
				"effective": effective,
				"status": "FAIL",
				"reason": "the default is not one of %s" % ", ".join(accepted),
			}
	print(frappe.as_json(rows, indent=1))
	return rows
