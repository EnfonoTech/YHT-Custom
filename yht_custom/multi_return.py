# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Return goods spanning several delivery notes in one pass.

WHY THIS EXISTS
A customer walks in with goods from three different delivery notes. ERPNext can
only return against ONE note at a time, because `Delivery Note.return_against` is
a single Link — verified: appending a row from a second note into one return SAVES
and SUBMITS without complaint, with `return_against` pointing at the first note
only and the second note never credited. That silent half-linkage is the trap this
screen removes: it still creates **one return per source note**, it just does all
of them from a single selection.

WHAT IT DOES NOT DO
It does not invent returnable quantities. The remaining qty per row is derived the
same way `sales_and_purchase_return.get_returned_qty_map_for_row` derives it —
`sum(abs(qty))` over SUBMITTED returns keyed on `dn_detail` — so this screen and
ERPNext's own over-return guard can never disagree. Reimplementing that arithmetic
is how a screen ends up offering a quantity that then fails at submit.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, strip_html

#: Everything that has to be true for a delivery note to be returnable at all.
#: `per_returned` is NOT among them: it is maintained by the status updater, and a
#: row-level remainder is the authority here, so a note still sitting at 0% with
#: every row already returned must be excluded anyway. The row maths below does it.
RETURNABLE_FILTERS = {"docstatus": 1, "is_return": 0}


def _returned_qty_by_row(customer: str, row_names: list) -> dict:
	"""``{delivery note item name: qty already returned}`` in ONE query.

	Mirrors `get_returned_qty_map_for_row`, which ERPNext calls once PER ROW. Per row
	is an N+1 against a customer with hundreds of notes, so this aggregates instead —
	same filters, same `sum(abs(qty))`, keyed on the same `dn_detail`.
	"""
	if not row_names:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT ri.dn_detail AS row_name, SUM(ABS(ri.qty)) AS qty
		FROM `tabDelivery Note Item` ri
		JOIN `tabDelivery Note` r ON r.name = ri.parent
		WHERE r.docstatus = 1 AND r.is_return = 1 AND r.customer = %s
		  AND ri.dn_detail IN %s
		GROUP BY ri.dn_detail
		""",
		(customer, row_names),
		as_dict=True,
	)
	return {r.row_name: flt(r.qty) for r in rows}


@frappe.whitelist()
def returnable_delivery_notes(customer: str) -> list:
	"""Every delivery note for `customer` with quantity still to come back.

	Uses `frappe.get_list`, NOT `get_all`: `get_list` applies
	`permission_query_conditions`, which is what stops a branch user seeing another
	branch's notes here. `get_all` would bypass it and leak the lot.
	"""
	if not customer:
		return []
	frappe.has_permission("Delivery Note", "read", throw=True)

	notes = frappe.get_list(
		"Delivery Note",
		filters=dict(RETURNABLE_FILTERS, customer=customer),
		fields=["name", "posting_date", "status", "currency", "grand_total"],
		order_by="posting_date desc, name desc",
		limit_page_length=0,
	)
	if not notes:
		return []

	names = [n.name for n in notes]
	rows = frappe.db.sql(
		"""
		SELECT name, parent, idx, item_code, item_name, uom, rate, qty
		FROM `tabDelivery Note Item`
		WHERE parent IN %s ORDER BY parent, idx
		""",
		(names,),
		as_dict=True,
	)
	returned = _returned_qty_by_row(customer, [r.name for r in rows])

	by_note = {}
	for row in rows:
		already = flt(returned.get(row.name))
		returnable = flt(row.qty) - already
		if returnable <= 0:
			continue
		by_note.setdefault(row.parent, []).append(
			{
				"row_name": row.name,
				"idx": row.idx,
				"item_code": row.item_code,
				"item_name": row.item_name,
				"uom": row.uom,
				"rate": flt(row.rate),
				"delivered": flt(row.qty),
				"returned": already,
				"returnable": returnable,
			}
		)

	out = []
	for note in notes:
		items = by_note.get(note.name)
		if not items:
			continue  # every row on it is fully returned already
		out.append(
			{
				"name": note.name,
				"posting_date": str(note.posting_date),
				"status": note.status,
				"currency": note.currency,
				"grand_total": flt(note.grand_total),
				"items": items,
			}
		)
	return out



def _invoices_billing(delivery_note: str) -> list:
	"""Submitted, non-return invoices that actually bill this delivery note.

	🔴 Direct evidence, NOT `per_billed`. That column is maintained by the status
	updater, and its sibling `per_returned` was observed sitting at 0 after three
	submitted partial returns — a percentage that can lag is not something to gate
	an accounting entry on.
	"""
	return frappe.db.sql_list(
		"""SELECT DISTINCT si.name
		   FROM `tabSales Invoice Item` sii
		   JOIN `tabSales Invoice` si ON si.name = sii.parent
		   WHERE sii.delivery_note = %s AND si.docstatus = 1 AND si.is_return = 0""",
		delivery_note,
	)


def _apply_selection(target, wanted):
	"""Keep only the selected rows on a mapped return, at the selected quantity.

	The mapper hands back EVERY still-returnable row at its full remainder. Rows the
	operator did not tick have to be REMOVED, not zeroed — a zero-qty row fails
	validation, and leaving one at full qty returns goods the customer kept.
	"""
	keep = []
	for row in target.items:
		qty = wanted.get(row.dn_detail)
		if not qty:
			continue
		row.qty = -abs(flt(qty))
		row.stock_qty = row.qty * flt(row.conversion_factor or 1)
		keep.append(row)
	target.items = keep
	for idx, row in enumerate(target.items, start=1):
		row.idx = idx
	return target


@frappe.whitelist()
def create_returns(customer, selections, submit=0, raise_credit_notes=0) -> dict:
	"""Create one delivery return per selected note, optionally submit and credit.

	Each note is processed inside its own SAVEPOINT. The batch is not atomic on
	purpose: these are independent returns against independent notes, and one bad
	note must not discard the good ones. Without the savepoint, a failed note's
	partial writes would still sit in the transaction while the next one runs.
	"""
	selections = json.loads(selections) if isinstance(selections, str) else selections
	submit, raise_credit_notes = cint(submit), cint(raise_credit_notes)

	frappe.has_permission("Delivery Note", "create", throw=True)
	if raise_credit_notes:
		frappe.has_permission("Sales Invoice", "create", throw=True)
	if raise_credit_notes and not submit:
		frappe.throw(_("A credit note can only be raised from a SUBMITTED return."))

	from erpnext.stock.doctype.delivery_note.delivery_note import (
		make_sales_invoice,
		make_sales_return,
	)

	results = []
	for index, selection in enumerate(selections or []):
		source = selection.get("delivery_note")
		wanted = {
			r["row_name"]: flt(r["qty"])
			for r in selection.get("rows", [])
			if flt(r.get("qty")) > 0
		}
		if not source or not wanted:
			continue

		save_point = "yht_multi_return_" + str(index)
		frappe.db.savepoint(save_point)
		try:
			# ⚠️ Per-DOCUMENT, not just per-doctype. Without this a branch user could
			# post a return against a note their permission_query_conditions hides.
			frappe.has_permission("Delivery Note", "create", doc=source, throw=True)
			if frappe.db.get_value("Delivery Note", source, "customer") != customer:
				frappe.throw(_("{0} does not belong to {1}.").format(source, customer))

			target = _apply_selection(make_sales_return(source), wanted)
			if not target.items:
				frappe.throw(_("Nothing selected on {0}.").format(source))
			target.save()
			row = {"delivery_note": source, "return": target.name, "credit_note": None}

			if submit:
				target.submit()
				if raise_credit_notes:
					# 🔴 NEVER credit a delivery note that was never invoiced.
					# Reproduced before this guard: KSDN-26-0541 had per_billed 0, the
					# screen still raised credit note KSIN-26-0614 for -13.80, and its
					# receivable GL posted Cr 14.00 — free credit to a customer who had
					# never been charged. The goods still come back; there is simply
					# nothing to credit.
					billed = _invoices_billing(source)
					if not billed:
						row["credit_note"] = None
						row["credit_skipped"] = _(
							"{0} was never invoiced, so there is nothing to credit."
						).format(source)
					else:
						credit = make_sales_invoice(target.name)
						credit.save()
						credit.submit()
						row["credit_note"] = credit.name
						row["settles"] = credit.return_against
						if not credit.return_against:
							# Billed by more than one invoice, so the link is ambiguous and
							# `link_credit_note_to_original_invoice` declined. The credit is
							# real, it just has to be matched by hand.
							row["credit_unlinked"] = _(
								"{0} is billed by {1} invoices, so the credit note could not be "
								"matched automatically. Reconcile it against the right invoice."
							).format(source, len(billed))
			results.append(row)
		except Exception as e:
			frappe.db.rollback(save_point=save_point)
			results.append(
				{
					"delivery_note": source,
					"error": type(e).__name__ + ": " + strip_html(str(e))[:300],
				}
			)

	return {
		"created": [r for r in results if not r.get("error")],
		"failed": [r for r in results if r.get("error")],
	}
