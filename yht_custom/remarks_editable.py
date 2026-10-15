# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Q&A 5 (meeting 2026-10-15) — the standard Remarks, editable after submit, with the history kept.

Client: "need to keep standard remarks editable after save, and the history of the edit added in the
activity below". On 2026-10-12 we had advised that "Other Remarks" was enough; the client's answer
is that the standard field is the one they mean.

Three parts:

1. `allow_on_submit` on the remarks field of Sales Invoice, Purchase Invoice, Purchase Receipt,
   Payment Entry and Stock Entry, and on Journal Entry's `user_remark` (Property Setters).
2. `track_changes` stays on (it is on upstream for all six; a Property Setter pins it), which is what
   writes the edit into the document's activity.
3. 🔴 THE LEDGER FOLLOWS. A GL Entry copies the wording when the document posts, so an edit after
   submit would leave the General Ledger and the Payment Ledger reading the old text while the
   document reads the new one. `on_update_after_submit` therefore rewrites that wording, TEXT ONLY, on
   the voucher's own rows: where a row's remarks contain the old wording it is replaced by the new
   (ERPNext puts "No Remarks" there when the field was blank, and a Journal Entry composes a row's
   remarks from its own text too, so a plain "replace the old with the new" is the rule that holds for
   all of them). No account, amount, date or posting changes, and `modified` is left alone.

Behind `oct15_std_remarks_editable`: the setters are written by the site's own provisioning, and the
handler does nothing until the switch is on.
"""

import frappe
from frappe.utils import cstr

from yht_custom import features

FEATURE = "oct15_std_remarks_editable"

#: doctype -> its standard remarks field.
FIELDS = {
	"Sales Invoice": "remarks",
	"Purchase Invoice": "remarks",
	"Purchase Receipt": "remarks",
	"Payment Entry": "remarks",
	"Stock Entry": "remarks",
	"Journal Entry": "user_remark",
}

#: What ERPNext writes into a ledger row when the document's remarks were blank.
BLANK_WORDING = "No Remarks"


def setup_standard_remarks_editable() -> dict:
	"""Make the six remarks fields editable after submit and pin change tracking. Idempotent."""
	if not features.enabled(FEATURE):
		return {"skipped": f"{FEATURE} is off for this site"}

	from yht_custom.form_layout import _set_property

	done, skipped = [], []
	for doctype, fieldname in FIELDS.items():
		if not frappe.db.exists("DocType", doctype) or not frappe.get_meta(doctype).get_field(fieldname):
			skipped.append(f"{doctype}.{fieldname}")
			continue
		_set_property(doctype, fieldname, "allow_on_submit", "1", "Check")
		_set_property(doctype, None, "track_changes", "1", "Check", for_doctype=True)
		frappe.clear_cache(doctype=doctype)
		done.append(f"{doctype}.{fieldname}")
	return {"editable": done, "skipped": skipped}


def _replace(text, old, new):
	return cstr(text).replace(old, new) if old and old in cstr(text) else cstr(text)


def sync_ledger_wording(doc, method=None):
	"""`on_update_after_submit` — the ledger rows read what the document now says."""
	if not features.enabled(FEATURE):
		return
	fieldname = FIELDS.get(doc.doctype)
	if not fieldname:
		return
	before = doc.get_doc_before_save()
	if not before:
		return

	old = cstr(before.get(fieldname)).strip()
	new = cstr(doc.get(fieldname)).strip()
	if old == new:
		return
	old_text, new_text = old or BLANK_WORDING, new or BLANK_WORDING

	for ledger in ("GL Entry", "Payment Ledger Entry"):
		if not frappe.get_meta(ledger).has_field("remarks"):
			continue
		for row in frappe.get_all(
			ledger,
			filters={"voucher_type": doc.doctype, "voucher_no": doc.name},
			fields=["name", "remarks"],
			limit=0,
		):
			wording = _replace(row.remarks, old_text, new_text)
			if wording != cstr(row.remarks):
				frappe.db.set_value(ledger, row.name, "remarks", wording, update_modified=False)
