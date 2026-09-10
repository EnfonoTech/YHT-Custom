# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Point a submitted Sales Invoice row back at the note that shipped it.

Client sheet item 32, and the scope is narrower than it looks. In the DN-first
flow ERPNext's own `delivery_note.make_sales_invoice` already writes
`delivery_note` and `dn_detail` onto the invoice at creation. The gap is the
**SI-first** flow: an invoice raised first, then a Delivery Note created from it
via `sales_invoice.make_delivery_note`, which writes `si_detail` /
`against_sales_invoice` onto the note and nothing back. That is exactly
KSIN-26-0701 / KSDN-26-0634.

🔴 THE LINK FIELDS ARE DELIBERATELY **NOT** `allow_on_submit`, and that reverses
the requirement (gate Q3, accepted). `frappe.db.set_value` is a direct UPDATE —
it never consults `allow_on_submit`, and `delivery_return.py` already does this
exact write on submitted invoices in production without it. Turning it on makes
things WORSE: `Document.update_children()` rewrites every child row on a
submitted-document save, so a form loaded before the link was written would then
**silently blank it** — and that link is what ERPNext's over-return guard
(`validate_returned_items` keys on `dn_detail`) and `update_billing_status`
depend on. With `allow_on_submit = 0` the same stale save is refused loudly with
`UpdateAfterSubmitError` and a reload fixes it. A loud refusal beats a silent
unlink.

🔴 ONE RESOLVER, CALLED FROM BOTH EVENTS. Submit and cancel do not each mutate
in their own direction — both ask `_resolve` the same question and write its
answer, so the handler is idempotent, a second delivery turns a link back into a
blank, and cancelling one of two turns an ambiguity back into a link, with no
separate code path to drift.

🔴 CANCEL ONLY EVER RUNS WHERE THE LINK IS ALREADY BLANK, AND THAT IS A REAL
WORKFLOW CHANGE FOR THE CLIENT. `DeliveryNote.on_cancel` calls
`check_next_docstatus()` (`erpnext/stock/doctype/delivery_note/delivery_note.py:517`,
`:701-709`), which refuses the cancel outright while ANY submitted Sales Invoice
row still carries `delivery_note = <this note>`. `doc_events` handlers run after
the controller method, so once `link_invoice_rows` has written that link the
cancel never reaches us:

* **one note ships the row** — the link is set, so the note can no longer be
  cancelled until its invoice is cancelled first. Before this item it could be.
  That is ERPNext's ordinary DN-first behaviour arriving in the SI-first flow,
  and it goes in the client note rather than being discovered.
* **two notes ship it** — `_resolve` blanked the link when the second was
  submitted, so `check_next_docstatus` finds nothing, the cancel proceeds and
  `unlink_invoice_rows` DOES run: it turns the ambiguity back into a link on the
  survivor. This is the case the handler exists for and it is live.

The unlink is deliberately NOT moved to `before_cancel`, where it would run ahead
of `check_next_docstatus` and blank the link so the cancel sails through. That is
a silent unlink of a submitted invoice to defeat an upstream guard, which is the
exact trade gate Q3 refused two paragraphs up. A loud refusal beats a silent
unlink here too.

WHAT THIS MODULE DOES NOT TOUCH, EXPLICITLY:

* The invoice row's delivered quantity. `DeliveryNote`'s own `status_updater`
  already maintains it — `{"source_dt": "Delivery Note Item", "target_dt":
  "Sales Invoice Item", "join_field": "si_detail", ...}` joins on exactly the
  field this module reads, and carries its own over-delivery guard. Writing it
  here would double-count against that guard.
* Any delivered-percentage field. Sales Invoice has none; the one in
  `sales_invoice.py` targets the **Sales Order**, and only when the invoice
  itself carries `update_stock`. There is nothing to write.
* The parent invoice. Never a document write on a submitted parent to change a
  child row, and `update_modified=False` so a note's submission does not make
  every open copy of the invoice stale.
"""

import frappe
from frappe.query_builder.functions import Count, Max
from frappe.utils import cint, cstr, flt


def _resolve(si_details) -> dict:
	"""``{si_detail: (delivery_note, dn_detail, qty)}`` for rows EXACTLY one note ships.

	Zero or more than one → absent from the map, which the caller reads as
	``(None, None)``. That single rule is the client's decision — blank rather
	than an arbitrary winner on a split delivery — and it is also what makes
	cancel correct without a second code path.

	ONE query however many rows the note carries, the same shape as item 25's
	`sales_flow._stock_document_against`, and for the same reason: this runs on
	every submit AND every cancel of every Delivery Note, and a twenty-line note
	is ordinary. `GROUP BY si_detail HAVING COUNT(*) = 1` puts the "exactly one"
	rule in the database rather than in a loop, so there is one place it can be
	wrong. `Max` is safe precisely because of that HAVING — the group is a single
	row, so the aggregate returns that row's own values.

	Counts only SUBMITTED, non-return notes. `on_cancel` fires after the parent's
	`docstatus` is already 2 in the database, so the note being cancelled has
	dropped out of this count by the time the handler asks.
	"""
	details = {cstr(value).strip() for value in (si_details or [])}
	details.discard("")
	if not details:
		return {}

	child = frappe.qb.DocType("Delivery Note Item")
	parent = frappe.qb.DocType("Delivery Note")
	rows = (
		frappe.qb.from_(child)
		.join(parent)
		.on(parent.name == child.parent)
		.select(
			child.si_detail,
			Max(child.parent).as_("note"),
			Max(child.name).as_("note_row"),
			Max(child.qty).as_("note_qty"),
		)
		.where(
			child.si_detail.isin(list(details))
			& (parent.docstatus == 1)
			& (parent.is_return == 0)
		)
		.groupby(child.si_detail)
		.having(Count(child.name) == 1)
	).run(as_dict=True)

	return {row.si_detail: (row.note, row.note_row, flt(row.note_qty)) for row in rows}


def _invoice_rows(doc):
	"""The submitted, forward Sales Invoice rows this note is allowed to write.

	One query. A row whose parent invoice is a return, is not submitted, or no
	longer exists simply does not come back.
	"""
	details = {cstr(row.get("si_detail")).strip() for row in (doc.get("items") or [])}
	details.discard("")
	if not details:
		return []

	item = frappe.qb.DocType("Sales Invoice Item")
	invoice = frappe.qb.DocType("Sales Invoice")
	return (
		frappe.qb.from_(item)
		.join(invoice)
		.on(invoice.name == item.parent)
		.select(item.name, item.qty, item.so_detail, item.delivery_note, item.dn_detail)
		.where(item.name.isin(list(details)) & (invoice.docstatus == 1) & (invoice.is_return == 0))
	).run(as_dict=True)


def _apply(doc):
	"""Write `_resolve`'s answer onto every row this note legitimately owns."""
	if cint(doc.get("is_return")):
		# 🔴 THE EXACT COMPLEMENT OF
		# `delivery_return.link_credit_note_to_delivery_return`, which is
		# registered on the SAME event and writes the SAME two fields. Neither may
		# ever run on the other's documents.
		return 0

	# 🔴 GATE Q4 — THE FINDING THAT MOST CHANGES THE SHAPE OF THIS ITEM.
	# `delivery_note.update_billed_amount_based_on_so` sums the invoice rows for a
	# Sales Order row `WHERE dn_detail IS NULL OR dn_detail = ''`, and then, for
	# each note row against that order row, does `if dnd.si_detail:
	# billed_against_so -= dnd.amount`. In the SI-first flow `dnd.si_detail` IS
	# set — so writing `dn_detail` here removes the amount from the sum AND
	# subtracts it again. `billed_against_so` goes negative, a later unbilled note
	# row against the same order picks up a negative billed amount, and its own
	# percentage and status flip. That is silent corruption of a submitted stock
	# document.
	#
	# Without `so_detail`, `update_billing_status` takes the
	# `if d.si_detail and not d.so_detail` branch, which reads the note's own row
	# and is untouched by anything written here. Measured on yht-khobhar
	# 2026-09-10: 48 of 116 candidate rows (41%) are skipped this way, and that
	# gap is accepted — patching ERPNext's billing attribution is its own item.
	rows = [row for row in _invoice_rows(doc) if not cstr(row.so_detail).strip()]
	if not rows:
		return 0

	resolved = _resolve(row.name for row in rows)

	written = 0
	for row in rows:
		note, note_row, note_qty = resolved.get(row.name, (None, None, 0.0))

		# 🔴 COUNT IS NOT COVERAGE. `_resolve`'s `HAVING COUNT(*) = 1` proves that
		# exactly one note row cites this invoice row — it says nothing about how
		# much of it shipped. A partial delivery (invoice 10, note 3) is one row,
		# so on count alone the invoice line would name a note that delivered
		# under a third of it, and `dn_detail` would then read as "this line was
		# shipped on that note" to anyone — and to ERPNext's own
		# `update_billing_status` — looking at it later.
		#
		# The note's OWN quantity is what is compared, deliberately — not the
		# running total ERPNext's StatusUpdater maintains on the invoice row. This
		# runs inside `on_submit`, and whether that total has been written for THIS
		# note yet depends on handler order; the note row's own quantity is true at
		# both events and needs no ordering assumption. That running total is also
		# never named literally anywhere in this module, deliberately: a test greps
		# the source for it to prove this module never writes it, and that guard is
		# cheap enough to be worth keeping strict rather than clever.
		if note and flt(note_qty) < flt(row.qty):
			note, note_row = None, None

		if (row.delivery_note or None, row.dn_detail or None) == (note, note_row):
			continue

		frappe.db.set_value(
			"Sales Invoice Item",
			row.name,
			{"delivery_note": note, "dn_detail": note_row},
			update_modified=False,
		)
		written += 1

	return written


def link_invoice_rows(doc, method=None):
	"""`Delivery Note.on_submit` — the invoice row now names this note."""
	return _apply(doc)


def unlink_invoice_rows(doc, method=None):
	"""`Delivery Note.on_cancel` — the same question, asked again.

	Not a reversal: `_resolve` re-answers with this note gone, which restores a
	link that a second note had made ambiguous.

	Reachable only when the link is already blank — `check_next_docstatus` refuses
	the cancel first otherwise. See the module docstring; that is the split
	delivery case, and it is the one this handler is for.
	"""
	return _apply(doc)
