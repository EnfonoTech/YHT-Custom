# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Client sheet, rows escalated 2026-10-26 — four things taken OFF the forms.

Every step hides a field and nothing else: no column is dropped, no Custom Field deleted, no value
cleared. That is deliberate (gotcha 22): a deleted Custom Field leaves its column and its text behind,
and the next field to reuse the name brings that text back under a new label. Hidden, the data stays
where it is and the request is one Property Setter (or one `hidden` flag) away from being reversed.

Each step is idempotent, never commits, and waits for its own `oct27_*` switch — the shared bench
serves the live site and UAT from one `apps/yht_custom` (gotcha 106).

* **Other Remarks** (row 22 undone). Measured on live 2026-10-27: 34 documents carry text in
  `custom_other_remarks` (Quotation 15, Payment Entry 6, Delivery Note 5, Journal Entry 4, Sales Order 3,
  Sales Invoice 1). It is never printed and never reaches the ledger, so hiding it changes no output.
  `meeting_1011.setup_requested_fields_visible` would un-hide it again on the next migrate, so it skips
  the field while this switch is on.
* **Payment Due Date on a Cash invoice.** `due_date` ships with no `depends_on`, so one Property Setter
  keyed on our `custom_payment_mode` is the whole change. The stored date is untouched: ERPNext still
  derives it from the payment terms, and the receivable ageing reads it.
* **Company Tax ID.** `company_tax_id` exists on Sales Invoice only (erpnext v15). Hidden on the form;
  the prints and the ZATCA XML read the value, not the form.
* **Attention.** Our CR-011 `custom_attention_person` on the four selling documents. A document that
  already carries a name still prints it; nobody can type a new one.
"""

import frappe

from yht_custom import features
from yht_custom.form_layout import _set_property

OTHER_REMARKS = "oct27_other_remarks_hidden"
CASH_DUE_DATE = "oct27_cash_hides_due_date"
COMPANY_TAX_ID = "oct27_company_tax_id_hidden"
ATTENTION = "oct27_attention_hidden"

#: Written once so the step and its test cannot disagree about the condition.
DUE_DATE_DEPENDS_ON = 'eval:doc.custom_payment_mode!=="Cash"'


def _hide_custom_field(doctype: str, fieldname: str) -> bool:
	"""Set `hidden = 1` on our own Custom Field. Returns True when it changed something."""
	name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "name")
	if not name or frappe.db.get_value("Custom Field", name, "hidden"):
		return False
	frappe.db.set_value("Custom Field", name, "hidden", 1)
	frappe.clear_cache(doctype=doctype)
	return True


def setup_other_remarks_hidden() -> dict:
	"""Row 22 undone — hide Other Remarks everywhere it was created, keep its text."""
	if not features.enabled(OTHER_REMARKS):
		return {"skipped": f"{OTHER_REMARKS} is off for this site"}

	from yht_custom.other_remarks import DOCTYPES, FIELDNAME

	hidden = [dt for dt in DOCTYPES if _hide_custom_field(dt, FIELDNAME)]
	return {"hidden": hidden}


def setup_cash_hides_due_date() -> dict:
	"""Payment Due Date disappears from a Sales Invoice whose Payment Mode is Cash."""
	if not features.enabled(CASH_DUE_DATE):
		return {"skipped": f"{CASH_DUE_DATE} is off for this site"}

	meta = frappe.get_meta("Sales Invoice")
	if not meta.has_field("custom_payment_mode"):
		# Without the field the condition reads undefined !== "Cash" = true: harmless, but a
		# setter that can never fire is a silent no-op, so say so instead (gotcha 31).
		frappe.log_error(title="yht_custom: cash due date", message="Sales Invoice has no custom_payment_mode")
		return {"skipped": "Sales Invoice has no custom_payment_mode"}

	_set_property("Sales Invoice", "due_date", "depends_on", DUE_DATE_DEPENDS_ON, "Code")
	frappe.clear_cache(doctype="Sales Invoice")
	return {"Sales Invoice.due_date": DUE_DATE_DEPENDS_ON}


def setup_company_tax_id_hidden() -> dict:
	"""The company's own Tax ID off the Sales Invoice form."""
	if not features.enabled(COMPANY_TAX_ID):
		return {"skipped": f"{COMPANY_TAX_ID} is off for this site"}
	if not frappe.get_meta("Sales Invoice").has_field("company_tax_id"):
		return {"skipped": "Sales Invoice has no company_tax_id"}

	_set_property("Sales Invoice", "company_tax_id", "hidden", "1", "Check")
	frappe.clear_cache(doctype="Sales Invoice")
	return {"Sales Invoice.company_tax_id": "hidden"}


def setup_attention_hidden() -> dict:
	"""The Attention line off the Address & Contact block of the selling documents."""
	if not features.enabled(ATTENTION):
		return {"skipped": f"{ATTENTION} is off for this site"}

	from yht_custom.attention_field import DOCTYPES, FIELDNAME

	hidden = [dt for dt in DOCTYPES if _hide_custom_field(dt, FIELDNAME)]
	return {"hidden": hidden}
