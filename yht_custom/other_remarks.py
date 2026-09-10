# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""`custom_other_remarks` — a note that can still be added after submit.

Client sheet item 28. Staff need somewhere to record why a document looks the
way it does *after* it has gone out, and to see the edit in the activity log.
So the field is `allow_on_submit`, and the four doctypes that ship with
`track_changes` off get it turned on — without a `Version` row there is nothing
for the activity log to show.

🔴 THE FIELDNAME IS `custom_other_remarks`, NOT `custom_remarks`. That name is
already taken on this site, twice and with two different fieldtypes: a **Check**
on Payment Entry from `zatca_vat_report`, and a **Small Text** on
`Opening Invoice Creation Tool Item` from our own `setup.py`. One fieldname
across all eleven doctypes, and it is this one.

**IT MUST NEVER REACH THE LEDGER.** `erpnext/controllers/accounts_controller.py`
stamps `self.get("remarks") or self.get("remark")` onto every GL Entry. Nothing
reads this field, so nothing needs writing to keep it off the ledger — but that
is an invariant, not an accident, and a test asserts it. This is a note. It
carries no accounting meaning and must not be used as an approval marker.

What does NOT happen, and materially reduces the risk of the whole item: an
update-after-submit save runs `before_update_after_submit` and
`on_update_after_submit` only — `frappe/model/document.py::run_before_save_methods`
skips `before_validate` and `validate` for that action. So `branch_guard`,
`fiscal_year`, `discount_totals` and the `update_stock` rules do not re-fire when
someone edits Other Remarks on a submitted document.
"""

import frappe

# The `doctype_or_field` trap lives in exactly one place. Re-implementing the
# upsert here is how a DocType-level Property Setter quietly ships as a DocField
# row that inserts cleanly, reports success and does nothing.
from yht_custom.form_layout import _set_property

#: Written down once so the field definition, the Delivery Note lock exemption,
#: the fixture list and the tests cannot drift apart.
FIELDNAME = "custom_other_remarks"

#: The eleven transaction doctypes from the client sheet.
DOCTYPES = (
	"Sales Invoice",
	"Purchase Invoice",
	"Delivery Note",
	"Purchase Receipt",
	"Payment Entry",
	"Journal Entry",
	"Sales Order",
	"Quotation",
	"Stock Entry",
	"Material Request",
	"Stock Reconciliation",
)

#: `Document.save_version()` returns early unless the DocType has
#: `track_changes = 1`, so without it the client's "view it in the activity log"
#: premise silently produces nothing. Upstream ships it on for seven of the
#: eleven and these four are the ones it has ever shipped off — erpnext has
#: since flipped `Stock Entry` on, which is exactly why the Property Setter is
#: written for all four rather than only for whichever are off this week. The
#: cost of turning it on is storage, not behaviour.
TRACK_CHANGES_OFF_UPSTREAM = ("Quotation", "Stock Entry", "Material Request", "Stock Reconciliation")

#: doctype → the anchors to try, in order.
#:
#: 🔴 AN `insert_after` THAT DOES NOT RESOLVE IS NOT AN ERROR — IT IS A SILENT
#: APPEND. `frappe/model/meta.py::_update_field_order_based_on_insert_after`
#: puts a custom field whose anchor it cannot find at the very END of the form,
#: with no complaint. A remarks box below the Amended From line is not what
#: anybody asked for, so every anchor is resolved against live meta and a
#: doctype whose anchor cannot be resolved is logged and SKIPPED instead.
#:
#: Six of the eleven have a remarks field of their own and the note belongs
#: beside it. Delivery Note has `instructions`. The remaining four have no free
#: text at all, so they fall back to `amended_from` — the one field every
#: submittable doctype carries, and (measured against upstream v15) near the top
#: of the form on all of them rather than at the bottom.
ANCHORS = {
	"Sales Invoice": ("remarks", "amended_from"),
	"Purchase Invoice": ("remarks", "amended_from"),
	"Purchase Receipt": ("remarks", "amended_from"),
	"Payment Entry": ("remarks", "amended_from"),
	"Stock Entry": ("remarks", "amended_from"),
	# `remark` beside it is system-generated; `user_remark` is the one a person
	# types, so the new note sits with that.
	"Journal Entry": ("user_remark", "amended_from"),
	"Delivery Note": ("instructions", "amended_from"),
	"Sales Order": ("amended_from",),
	"Quotation": ("amended_from",),
	"Material Request": ("amended_from",),
	"Stock Reconciliation": ("amended_from",),
}

DESCRIPTION = (
	"A note only. It can be edited after the document is submitted and the change is "
	"recorded in the activity log. It does not appear on the print, and it never reaches "
	"the ledger."
)


def _field(insert_after):
	return {
		"fieldname": FIELDNAME,
		"label": "Other Remarks",
		"fieldtype": "Small Text",
		"insert_after": insert_after,
		"allow_on_submit": 1,
		# Deliberately copied onto an amended or duplicated document: the note
		# explains the transaction, and the amendment is the same transaction.
		"no_copy": 0,
		"print_hide": 1,
		"description": DESCRIPTION,
	}


def _resolve_anchor(meta, candidates):
	"""The first candidate that exists AND is not the last field on the form.

	The second half matters as much as the first: landing after the last field is
	indistinguishable from the silent append an unresolvable anchor produces.
	"""
	order = [df.fieldname for df in meta.fields]
	if not order:
		return None
	for candidate in candidates:
		if candidate in order and order[-1] != candidate:
			return candidate
	return None


def ensure_other_remarks_fields():
	"""One Small Text per doctype, plus `track_changes` where upstream lacks it.

	Its own `PROVISIONING_STEPS` entry, so a failure on one doctype's anchor is
	reported as itself rather than hidden behind another item's exception.
	"""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	fields, unresolved = {}, []

	for doctype in DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			unresolved.append(f"{doctype}: no such doctype")
			continue
		anchor = _resolve_anchor(frappe.get_meta(doctype), ANCHORS.get(doctype, ("amended_from",)))
		if not anchor:
			unresolved.append(f"{doctype}: no usable anchor in {ANCHORS.get(doctype)}")
			continue
		fields[doctype] = [_field(anchor)]

	if fields:
		create_custom_fields(fields, ignore_validate=True)

	# ⚠️ WRITTEN WHETHER OR NOT THE DOCTYPE ALREADY SHIPS IT ON, AND THAT IS
	# DELIBERATE. Upstream does not agree with itself about this set: `Stock
	# Entry` was flipped to `track_changes = 1` by erpnext's *"[minor] track
	# changes for transaction documents"* and Quotation, Material Request and
	# Stock Reconciliation were not, so a step that skipped a doctype already
	# carrying the flag would leave the guarantee resting on the erpnext version
	# installed that week. The Property Setter is what makes it OURS: a future
	# upstream flip back to 0 cannot silently take the activity log away with it.
	# Where upstream already agrees the row is a behavioural no-op, and
	# `_set_property` writes it once and then finds it every time.
	for doctype in TRACK_CHANGES_OFF_UPSTREAM:
		if doctype not in fields:
			# The field itself was skipped, so there is nothing here to version.
			continue
		_set_property(doctype, None, "track_changes", "1", "Check", for_doctype=True)

	if unresolved:
		frappe.log_error(message="\n".join(unresolved), title="yht_custom: other remarks")

	return {"created_for": sorted(fields), "unresolved": unresolved}
