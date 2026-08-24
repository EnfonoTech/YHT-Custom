# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Item 5 of the client sheet — a fetched rate is not editable.

"If sales invoice is made through get item from sales order, delivery notes,
sales quotation, Rate should be uneditable."

The point is commercial, not cosmetic: a rate agreed on the order and delivered
against must be the rate invoiced. Today it is freely typeable, and 14,401 of
12,474 invoice rows arrive from a source document (6,021 from a Sales Order,
8,380 from a Delivery Note — rows can carry both), so this is the normal path
rather than an edge case.

WHERE THE BOUNDARY IS. `branch_user_forms.js` makes the cell read-only, and that
is UX only — it does not survive `frappe.client.set_value`, a Data Import, or a
Server Script. This module is the boundary, on `validate`, the same shape as
`branch_guard`.

WHO CAN OVERRIDE. The same bypass roles the rest of the app honours. Somebody has
to be able to correct a genuinely wrong order rate without cancelling the chain;
a branch operator is not that somebody.
"""

import frappe
from frappe import _
from frappe.utils import flt

from yht_custom.sales_flow import _may_bypass

#: (row fieldname holding the source row's name, its doctype). Checked in order;
#: the first one populated wins, because a row invoiced from a Delivery Note that
#: itself came from a Sales Order carries BOTH and the delivery note is the nearer
#: document.
SOURCES = (
	("dn_detail", "Delivery Note Item"),
	("so_detail", "Sales Order Item"),
)

#: Rounding tolerance, in the document's currency. Two paths that should agree can
#: still differ in the last halala after a UOM conversion.
TOLERANCE = 0.005


def enforce_fetched_rate(doc, method=None):
	"""Reject an edited rate on a row that came from another document."""
	if doc.get("is_return"):
		# A credit note mirrors the original and is allowed to restate it.
		return
	if _may_bypass():
		return

	wanted = _source_rates(doc)
	if not wanted:
		return

	for row in doc.get("items") or []:
		source_rate = wanted.get(_row_key(row))
		if source_rate is None:
			continue
		if abs(flt(row.rate) - flt(source_rate)) <= TOLERANCE:
			continue

		frappe.throw(
			_("Row #{0}: rate {1} does not match {2} on the source document. "
			  "The rate is set where the order was agreed, not here.").format(
				row.idx, flt(row.rate), flt(source_rate)
			),
			title=_("Rate is fixed by the source document"),
		)


def _row_key(row):
	for fieldname, _doctype in SOURCES:
		value = row.get(fieldname)
		if value:
			return (fieldname, value)
	return None


def _source_rates(doc) -> dict:
	"""One query per source doctype, never one per row.

	A twenty-line invoice would otherwise be twenty round trips — the N+1 the
	house rules call a blocker.
	"""
	wanted = {}
	for fieldname, doctype in SOURCES:
		names = [row.get(fieldname) for row in (doc.get("items") or []) if row.get(fieldname)]
		if not names:
			continue
		for source in frappe.get_all(
			doctype, filters={"name": ["in", list(set(names))]}, fields=["name", "rate"]
		):
			wanted[(fieldname, source.name)] = source.rate
	return wanted
