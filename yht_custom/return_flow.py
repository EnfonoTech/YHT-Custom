# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Return policy for the four return-capable doctypes, in one place.

Three things live here, and they are separate on purpose:

* :func:`negate_return_quantities` — an operator who ticks *Is Return* and types
  a quantity gets the sign flipped for them, instead of a validation error.
* :func:`enforce_return_stock_route` — the `is_return` half of the
  delivery-note rule, which `sales_flow.enforce_delivery_note_route` never had.
* :func:`delivery_note_dashboard` — the Delivery Note ↔ Delivery Note link
  ERPNext omits, so a delivery return is visible from the note it reverses.

WHY A RETURN NEEDS ITS OWN RULE
The forward rule is "stock leaves on a Delivery Note, the invoice only bills what
already went out", and it is absolute. Reversing it is not symmetric, because how
the goods LEFT decides how they can come back:

* the original was delivered on a Delivery Note → the goods come back on a
  DELIVERY RETURN, and the credit note bills that. `update_stock` stays 0.
* the original carried its own stock (`update_stock = 1`, 950 legacy invoices on
  this site plus every pre-cutover `VTSI-`) → there is no Delivery Note to return
  against, so the goods come back on the credit note itself and `update_stock`
  must stay 1.

ERPNext already enforces the second half of that: `sales_and_purchase_return.py`
throws *'Update Stock' can not be checked because items are not delivered via …*
when a return ticks `update_stock` and its original did not. So the flag is not a
free choice — it is dictated by the original — which is exactly why
`enforce_delivery_note_route` zeroing it unconditionally was wrong: for a branch
user it meant the goods on a legacy direct-stock invoice could never come back at
all. Measured before the fix: `is_return=1, update_stock=1` went into the hook and
came out `update_stock=0`.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

#: Quantity fields to flip per doctype — the SAME set ERPNext's own mapper
#: negates in `sales_and_purchase_return.make_return_doc.update_item`, so a
#: hand-built return ends up shaped like a mapped one. Deriving these instead of
#: copying them is how a return passes `validate` and then fails at `on_submit`.
NEGATE_FIELDS = {
	"Sales Invoice": ("qty", "stock_qty"),
	"Delivery Note": ("qty", "stock_qty"),
	"Purchase Invoice": ("qty", "stock_qty", "received_qty", "rejected_qty"),
	"Purchase Receipt": (
		"qty",
		"stock_qty",
		"received_qty",
		"rejected_qty",
		"received_stock_qty",
	),
}

#: doctype → (item fieldname holding the stock document, that stock doctype).
#: Used to answer "did the goods come back on a stock document?"
STOCK_LINK = {
	"Sales Invoice": ("delivery_note", "Delivery Note"),
	"Purchase Invoice": ("purchase_receipt", "Purchase Receipt"),
}


def negate_return_quantities(doc, method=None):
	"""`before_validate` — flip a positive quantity on a return to negative.

	ERPNext rejects it instead: `StatusUpdater.validate_qty` throws *"For an item
	{0}, quantity must be negative number"*. Nothing in ERPNext negates a typed
	quantity — the only automatic negation is the Create > Return mapper, which
	an operator ticking the box by hand never goes through.

	⚠️ ONLY POSITIVE → NEGATIVE, never the reverse. A mapped return already
	arrives negative, and flipping again would turn every credit note into a sale.

	⚠️ WHERE THIS RUNS MATTERS. The sign check fires at `validate()` for Sales and
	Purchase Invoice but only at `on_submit()` for Delivery Note and Purchase
	Receipt, so `before_validate` is the one event that lands ahead of all four.
	On Purchase Invoice it must also run AFTER `expense_invoice.before_validate`,
	which stamps `qty = 1` on a blank row — a positive 1, on a return.
	"""
	if not cint(doc.get("is_return")):
		return

	fields = NEGATE_FIELDS.get(doc.doctype)
	if not fields:
		return

	flipped = False
	for row in doc.get("items") or []:
		for fieldname in fields:
			if not row.meta.has_field(fieldname):
				continue
			value = flt(row.get(fieldname))
			if value > 0:
				row.set(fieldname, -value)
				if fieldname == "qty":
					flipped = True

	if flipped:
		frappe.msgprint(
			_("This is a return, so the quantities have been made negative."),
			indicator="blue",
			alert=True,
		)


def _original_moved_its_own_stock(doc) -> bool | None:
	"""Did the document this one reverses carry its own stock?

	``None`` means "no original to ask" — a standalone credit note.
	"""
	ref = cstr(doc.get("return_against"))
	if not ref:
		return None
	if not frappe.db.exists(doc.doctype, ref):
		return None
	return bool(cint(frappe.db.get_value(doc.doctype, ref, "update_stock")))


def _came_back_on_a_stock_return(doc) -> bool:
	"""True when a row points at a stock document that is itself a return."""
	link = STOCK_LINK.get(doc.doctype)
	if not link:
		return False
	fieldname, stock_doctype = link

	names = {cstr(row.get(fieldname)) for row in doc.get("items") or []}
	names.discard("")
	if not names:
		return False

	# One query, not one per row. `limit_page_length`, not `limit` — get_all sets
	# the former and only the former is part of the query API.
	return bool(
		frappe.get_all(
			stock_doctype,
			filters={"name": ("in", list(names)), "is_return": 1},
			pluck="name",
			limit_page_length=1,
		)
	)


def enforce_return_stock_route(doc, method=None):
	"""`before_validate` — the return half of the delivery-note rule.

	Client decision, 2026-08-26: **a credit note means goods physically coming
	back.** So a return of a delivered document has to be raised on the stock
	document, not on the invoice — which is also the only route that links the two
	well enough for ERPNext's own over-return guard to fire (that guard keys on
	``dn_detail``; with it blank a second full return passes with a message
	instead of an error).

	⚠️ The evidence does not entirely agree with the decision, and this is the
	place to say so: 8 submitted returns on this site have no `return_against` at
	all, and 11 span between 2 and 23 source Delivery Notes. Those look like
	pricing credits rather than goods coming back. They are left to a bypass role
	rather than made impossible.
	"""
	from yht_custom.sales_flow import _may_bypass

	if not cint(doc.get("is_return")):
		return
	if doc.doctype not in STOCK_LINK:
		return
	if _may_bypass():
		return

	moved_own_stock = _original_moved_its_own_stock(doc)

	if moved_own_stock:
		# The original carried its own stock, so this document is where the goods
		# come back. Leave `update_stock` exactly as the mapper copied it — the
		# forward rule must NOT zero it here, or the stock never returns.
		return

	# Everything below is a return of goods that left on a stock document.
	doc.update_stock = 0

	if _came_back_on_a_stock_return(doc):
		return

	if moved_own_stock is None:
		frappe.throw(
			_(
				"A credit note has to say which document it reverses. Open the "
				"delivery return and use <b>Create &gt; Sales Invoice</b>, or tick "
				"<b>Issue Credit Note</b> on the delivery return so it is raised for you."
			),
			title=_("Return Against Required"),
		)

	frappe.throw(
		_(
			"These goods were delivered on a Delivery Note, so they have to come back "
			"on one. Open the Delivery Note, use <b>Create &gt; Sales Return</b>, and "
			"tick <b>Issue Credit Note</b> — the credit note is then raised and linked "
			"for you."
		),
		title=_("Deliver the Return First"),
	)


def delivery_note_dashboard(data=None):
	"""`override_doctype_dashboards` — put a delivery return on its original.

	🔴 ERPNext's `delivery_note_dashboard.py` has NO "Delivery Note" entry in any
	transactions group, so `return_against` is never surfaced: a delivery return
	does not appear in the Connections of the note it reverses, and the original
	does not appear on the return. Measured — `get_open_count` for a note with a
	submitted return against it reports no Delivery Note row at all. The Sales
	Invoice dashboard does the equivalent through
	``non_standard_fieldnames["Sales Invoice"] = "return_against"``; this is that,
	for Delivery Note.
	"""
	data = dict(data or {})

	fieldnames = dict(data.get("non_standard_fieldnames") or {})
	fieldnames["Delivery Note"] = "return_against"
	data["non_standard_fieldnames"] = fieldnames

	groups = [dict(g) for g in (data.get("transactions") or [])]

	# Already there (a future ERPNext could add it) — leave the dashboard alone.
	if any("Delivery Note" in (g.get("items") or []) for g in groups):
		data["transactions"] = groups
		return data

	# Prefer the existing Returns group. Matching on the label is safe because the
	# dashboard dict is built in the same request, so both sides are translated
	# the same way — but fall back to a new group rather than assume it.
	for group in groups:
		if group.get("label") == _("Returns"):
			group["items"] = [*(group.get("items") or []), "Delivery Note"]
			break
	else:
		groups.append({"label": _("Returns"), "items": ["Delivery Note"]})

	data["transactions"] = groups
	return data


# ----------------------------------------------------------------- diagnostics


@frappe.whitelist()
def return_gaps() -> dict:
	"""What is wrong with the returns already on this site.

	Reported rather than repaired: every one of these is a submitted document, and
	three of the four need a human to decide what the right answer was. Run with
	``bench --site … execute yht_custom.return_flow.return_gaps``.
	"""
	frappe.only_for(("Accounts Manager", "System Manager", "Stock Manager"))

	# 1. Goods came back and nobody credited them.
	uncredited = frappe.db.sql(
		"""
		SELECT dn.name, dn.posting_date, dn.customer, dn.grand_total
		FROM `tabDelivery Note` dn
		WHERE dn.is_return = 1 AND dn.docstatus = 1
		  AND NOT EXISTS (
			SELECT 1 FROM `tabSales Invoice Item` sii
			JOIN `tabSales Invoice` si ON si.name = sii.parent AND si.docstatus = 1
			WHERE sii.delivery_note = dn.name
		  )
		ORDER BY dn.posting_date
		""",
		as_dict=True,
	)

	# 2. Flagged as moving stock, but no stock moved.
	no_stock = frappe.db.sql(
		"""
		SELECT si.name, si.posting_date, si.customer
		FROM `tabSales Invoice` si
		WHERE si.is_return = 1 AND si.docstatus = 1 AND si.update_stock = 1
		  AND NOT EXISTS (
			SELECT 1 FROM `tabStock Ledger Entry` sle
			WHERE sle.voucher_type = 'Sales Invoice' AND sle.voucher_no = si.name
			  AND sle.is_cancelled = 0
		  )
		ORDER BY si.posting_date
		""",
		as_dict=True,
	)

	# 3. No original, so ERPNext's return validations never ran at all —
	#    `validate_return` returns immediately when `return_against` is blank.
	no_original = frappe.get_all(
		"Sales Invoice",
		filters={"is_return": 1, "docstatus": 1, "return_against": ("in", ("", None))},
		fields=["name", "posting_date", "customer", "grand_total"],
		order_by="posting_date",
	)

	# 4. The credit note points at the note that SHIPPED the goods, not at one
	#    that took them back — which is `make_return_doc` copying the source row's
	#    `delivery_note` verbatim. Harmless on its own, but it is why the
	#    over-return guard has nothing useful to count.
	points_at_outbound = frappe.db.sql(
		"""
		SELECT DISTINCT si.name, si.posting_date, si.customer
		FROM `tabSales Invoice` si
		JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
		JOIN `tabDelivery Note` dn ON dn.name = sii.delivery_note
		WHERE si.is_return = 1 AND si.docstatus = 1 AND dn.is_return = 0
		ORDER BY si.posting_date
		""",
		as_dict=True,
	)

	return {
		"delivery_returns_never_credited": {"count": len(uncredited), "rows": uncredited},
		"returns_flagged_update_stock_with_no_stock": {"count": len(no_stock), "rows": no_stock},
		"returns_with_no_original": {"count": len(no_original), "rows": no_original},
		"returns_pointing_at_the_outbound_note": {
			"count": len(points_at_outbound),
			"rows": points_at_outbound[:50],
		},
	}
