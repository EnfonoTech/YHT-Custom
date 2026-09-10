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

#: doctype → the item fieldname the return mapper stamps with the ORIGINAL row's name.
#: ERPNext's over-return guard keys on exactly this; with it blank a second full return
#: saves with a msgprint instead of an error, so a stock-moving return that does not
#: carry it can post any item at any quantity. Measured on this site: 145 of 145 rows on
#: stock-moving returns already have it, so requiring it rejects nothing real.
RETURN_ROW_LINK = {
	"Sales Invoice": "sales_invoice_item",
	"Purchase Invoice": "purchase_invoice_item",
}

#: Per-side wording. The handler is registered on BOTH invoice doctypes, and a buyer
#: returning goods to a supplier has no Delivery Note, no "Sales Return" menu entry and
#: no "Issue Credit Note" checkbox — sales-side text there is an instruction they cannot
#: follow.
ROUTE_MESSAGE = {
	"Sales Invoice": (
		"Deliver the Return First",
		"These goods were delivered on a Delivery Note, so they have to come back on one. "
		"Open the Delivery Note, use <b>Create &gt; Sales Return</b>, and tick "
		"<b>Issue Credit Note</b> — the credit note is then raised and linked for you.",
	),
	"Purchase Invoice": (
		"Return the Goods First",
		"These goods arrived on a Purchase Receipt, so they have to go back on one. "
		"Open the Purchase Receipt and use <b>Create &gt; Return</b>, then raise the debit "
		"note from that return.",
	),
}


#: doctype → how to walk a credit/debit note BACK to the invoice it reverses.
#:
#: `Delivery Note.issue_credit_note` builds the credit note with
#: `make_sales_invoice(<the delivery RETURN>)`, so the mapper's source is a stock
#: document and there is no invoice to put in `return_against` — that field is a
#: Sales Invoice link. The note is therefore standalone, and two things follow that
#: look like bugs to an operator:
#:
#: * the original invoice stays **Unpaid**. Both documents carry
#:   `update_outstanding_for_self = 1`, so each keeps its own outstanding against
#:   itself (measured: KSIN-26-0610 Dr 3.00 vs KSSR-26-0031 Cr 3.00, each with
#:   `against_voucher` pointing at itself). The customer's NET balance is right;
#:   per-invoice both sit open.
#: * **Connections shows no link**, because the Sales Invoice ↔ Sales Invoice
#:   "Returns" link keys on `return_against`.
#:
#: The two sides are NOT symmetric and neither field survives a guess — both were
#: read off the live meta: `Delivery Note Item` has `dn_detail` and NO
#: `delivery_note_item`; `Purchase Receipt Item` has `purchase_receipt_item` and NO
#: `pr_detail`. :func:`assert_backlink_fields_exist` pins all of them.
CREDIT_NOTE_BACKLINK = {
	"Sales Invoice": {
		"party_field": "customer",
		"stock_doctype": "Delivery Note",
		"stock_field": "delivery_note",
		"stock_row_doctype": "Delivery Note Item",
		"stock_row_field": "dn_detail",
		"stock_row_backlink": "dn_detail",
		"row_link": "sales_invoice_item",
	},
	"Purchase Invoice": {
		"party_field": "supplier",
		"stock_doctype": "Purchase Receipt",
		"stock_field": "purchase_receipt",
		"stock_row_doctype": "Purchase Receipt Item",
		"stock_row_field": "pr_detail",
		"stock_row_backlink": "purchase_receipt_item",
		"row_link": "purchase_invoice_item",
	},
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
	"""True when EVERY row points at a stock document that is itself a return.

	⚠️ Every, not any. The first version asked whether one row was linked and let the
	whole document through — so a single legitimate line could carry an unlimited
	number of unrelated ones past the guard, and that was also the one path that
	admitted a return with `return_against` blank, which switches off ERPNext's own
	party, date and over-return checks entirely.
	"""
	link = STOCK_LINK.get(doc.doctype)
	if not link:
		return False
	fieldname, stock_doctype = link

	rows = doc.get("items") or []
	if not rows:
		return False

	names = {cstr(row.get(fieldname)) for row in rows}
	if "" in names:
		return False  # a row with no stock document behind it at all

	# One query, not one per row.
	returns = set(
		frappe.get_all(
			stock_doctype,
			filters={"name": ("in", list(names)), "is_return": 1},
			pluck="name",
			limit_page_length=0,
		)
	)
	return names <= returns


def _original_shipped_on_a_stock_document(doc) -> bool:
	"""Did the document being reversed actually move goods on a stock document?

	This is the question the first version never asked, and the omission was a
	blocker: it treated "the original did not carry its own stock" as proof that the
	goods had gone out on a Delivery Note, when it equally means the original moved
	no goods at all. Measured on this site, that mistake refused returns against 345
	expense invoices, 366 purchase invoices with no receipt and 150 sales invoices
	with no delivery note.
	"""
	ref = cstr(doc.get("return_against"))
	if not ref:
		return False
	fieldname, _stock_doctype = STOCK_LINK[doc.doctype]
	return bool(
		frappe.get_all(
			f"{doc.doctype} Item",
			filters={"parent": ref, "parenttype": doc.doctype, fieldname: ("is", "set")},
			pluck="name",
			limit_page_length=1,
		)
	)


def _require_rows_mapped_from_the_original(doc):
	"""A stock-moving return must be built FROM the original document.

	Otherwise the rows carry no `RETURN_ROW_LINK`, ERPNext's over-return guard has no
	key to count against, and the return posts whatever item and quantity was typed —
	including items that never appeared on the invoice being reversed.
	"""
	fieldname = RETURN_ROW_LINK.get(doc.doctype)
	if not fieldname:
		return
	unlinked = [cint(row.idx) for row in doc.get("items") or [] if not cstr(row.get(fieldname))]
	if not unlinked:
		return

	frappe.throw(
		_(
			"Row {0}: a return that brings stock back has to be raised from the document "
			"it reverses — open {1} and use <b>Create &gt; Return</b>. Typing the rows by "
			"hand leaves nothing to check the quantity against."
		).format(", ".join(str(i) for i in unlinked), cstr(doc.get("return_against")) or _("the original")),
		title=_("Raise the Return From the Original"),
	)


def enforce_return_stock_route(doc, method=None):
	"""`before_validate` — the return half of the delivery-note rule.

	Client decision, 2026-08-26: **a credit note means goods physically coming back.**
	So a return of DELIVERED goods has to be raised on the stock document — which is
	also the only route that links the two well enough for ERPNext's own over-return
	guard to fire (that guard keys on the row link; with it blank a second full return
	passes with a message instead of an error).

	🔴 THREE THINGS THE FIRST VERSION GOT WRONG, all measured on this site:

	1. It read "the original did not carry its own stock" as "the goods went out on a
	   Delivery Note". It equally means the original moved NO goods — a service line, a
	   non-stock item, an expense bill. That refused returns against 345 expense
	   invoices, 366 purchase invoices with no receipt and 150 sales invoices with no
	   delivery note, and for an expense bill it was unsatisfiable by construction:
	   `Purchase Receipt Item.item_code` is mandatory and `Purchase Invoice Item`'s is
	   not, which is precisely why an expense invoice is a flagged Purchase Invoice.
	2. It returned the moment the original carried its own stock, leaving `update_stock`
	   exactly as typed and never looking at the return's own rows — so a branch user
	   could tick *Is Return* against any of 950 legacy direct-stock invoices and post
	   ANY item at ANY quantity into the warehouse. On the purchase side the same hole
	   ran stock OUT, with strictly less protection: ERPNext's own `update_stock` check
	   in `validate_return_against` is written `if doc.doctype == "Sales Invoice"`.
	3. Both messages were sales-side, on a handler registered for Purchase Invoice too.

	⚠️ The evidence still argues with the decision, and this is the place to say so: 8
	submitted returns have no `return_against` at all and 11 span 2 to 23 source
	delivery notes. Those look like pricing credits rather than goods coming back. They
	are left to a bypass role rather than made impossible.
	"""
	from yht_custom.sales_flow import _may_bypass

	if not cint(doc.get("is_return")):
		return
	if doc.doctype not in STOCK_LINK:
		return

	# 🔴 BEFORE THE BYPASS, AND THAT PLACEMENT IS THE WHOLE FIX. Client sheet item 25
	# ships `update_stock` with `default = 1`, and `get_mapped_doc` copies field
	# defaults onto the target — so from that change on, EVERY credit note arrives
	# ticked. `erpnext/controllers/sales_and_purchase_return.py:77` then throws
	# *"'Update Stock' can not be checked because items are not delivered via {0}"*
	# whenever a return carries `update_stock` and its original did not.
	#
	# Everything below this point is a POLICY the bypass roles are exempt from. This
	# is not: it is the arithmetic of the document. Left after the bypass check, a
	# System Manager / Stock Manager / Accounts Manager — i.e. exactly the roles that
	# raise credit notes — got the hard throw and could not raise one at all, while a
	# Branch User could. Left after the expense and "nothing was ever shipped" early
	# returns, the same throw came back for a service invoice. An exemption from a
	# policy must not become an exemption from correctness.
	#
	# The condition MIRRORS erpnext's own: zero it unless the document being reversed
	# genuinely moved its own stock, which is the only case where the goods come back
	# on this document. Zeroing can only ever prevent that throw; it can never turn a
	# saveable return into an unsaveable one.
	if cint(doc.get("update_stock")) and not _original_moved_its_own_stock(doc):
		doc.update_stock = 0

	if _may_bypass():
		return

	# An expense bill is itemless by design and can never have a stock document behind
	# it, so there is no route to demand. `enforce_purchase_receipt_route` exempts it
	# first thing for the same reason; this had no such exemption and made an expense
	# debit note unsaveable — while the same commit taught `set_expense_series` to give
	# that document the branch debit-note series. The two halves contradicted.
	if cint(doc.get("custom_is_expense_invoice")):
		return

	if _original_moved_its_own_stock(doc):
		# The goods come back on THIS document. Leave `update_stock` as the mapper
		# copied it — the forward rule must not zero it, or the stock never returns —
		# but only for rows that genuinely came from the original.
		_require_rows_mapped_from_the_original(doc)
		return

	if not _original_shipped_on_a_stock_document(doc):
		# Nothing was ever shipped or received: a service, a non-stock item, an expense.
		# There are no goods to come back, so there is no stock route to insist on.
		return

	doc.update_stock = 0

	if _came_back_on_a_stock_return(doc):
		return

	# The credit-note-first route, for a branch that has opted into it.
	#
	# The rule above is a client POLICY — "a credit note means goods physically coming
	# back" — not a correctness requirement, and some branches work the other way round:
	# credit the invoice, then bring the stock back on a delivery return raised from the
	# credit note. `update_stock` is already 0 by this point, so the note itself still
	# moves nothing; `yht_custom.delivery_return` is what moves it, and that refuses to
	# run unless every row traces back to one delivery note, which is the same link
	# ERPNext's over-return guard counts against.
	#
	# Sales side only. The purchase side has no equivalent entry point, and the message
	# it would otherwise get is an instruction a buyer cannot follow.
	if doc.doctype == "Sales Invoice":
		from yht_custom.yht_custom.doctype.yht_return_settings.yht_return_settings import (
			allow_delivery_note_from_sales_return,
		)

		if allow_delivery_note_from_sales_return():
			return

	title, message = ROUTE_MESSAGE[doc.doctype]
	frappe.throw(_(message), title=_(title))


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


def assert_backlink_fields_exist():
	"""Fail loudly if any field :data:`CREDIT_NOTE_BACKLINK` walks has gone away.

	Every entry here is a fieldname on someone else's doctype. A silent rename
	upstream would turn :func:`link_credit_note_to_original_invoice` into a no-op
	that leaves credit notes unlinked WITHOUT any error — the exact failure this
	function exists to prevent, and one that hid for a week the last time it bit us.
	"""
	missing = []
	for doctype, config in CREDIT_NOTE_BACKLINK.items():
		checks = (
			(f"{doctype} Item", config["stock_field"]),
			(f"{doctype} Item", config["stock_row_field"]),
			(f"{doctype} Item", config["row_link"]),
			(config["stock_row_doctype"], config["stock_row_backlink"]),
			(doctype, config["party_field"]),
			(doctype, "return_against"),
		)
		for target, fieldname in checks:
			if not frappe.get_meta(target).get_field(fieldname):
				missing.append(f"{target}.{fieldname}")
	return missing


def _original_invoice_row_for(row, config) -> tuple[str, str] | None:
	"""Walk one credit-note row back to the invoice row it reverses.

	credit row → the stock RETURN's row → the ORIGINAL stock row → the invoice row
	that billed it. Returns ``(invoice, invoice_row)`` or ``None`` when any link in
	that chain is absent, which is the normal shape of a hand-typed credit note.
	"""
	stock_doc = row.get(config["stock_field"])
	stock_row = row.get(config["stock_row_field"])
	if not stock_doc or not stock_row:
		return None

	# Only a note mapped from a RETURN needs rescuing. One mapped from a forward
	# stock document is a first-time bill, not a reversal.
	if not cint(frappe.db.get_value(config["stock_doctype"], stock_doc, "is_return")):
		return None

	original_stock_row = frappe.db.get_value(
		config["stock_row_doctype"], stock_row, config["stock_row_backlink"]
	)
	if not original_stock_row:
		return None

	candidates = frappe.db.get_all(
		f"{config['_doctype']} Item",
		filters={config["stock_row_field"]: original_stock_row, "docstatus": 1},
		fields=["name", "parent"],
	)
	# ⚠️ A credit note ALREADY raised against the same original row carries the very
	# same stock-row link, so it comes back here too and must not be mistaken for the
	# invoice being reversed. Measured on this site: original row 177m1l8c9h matches
	# BOTH KSIN-24-6950 and the credit note KSSR-24-1027. Filtering returns out after
	# picking a candidate is too late — the ambiguity has to go before the count.
	forward = [
		row
		for row in candidates
		if not cint(frappe.db.get_value(config["_doctype"], row.parent, "is_return"))
	]
	# An original billed by two invoices cannot be reversed against just one.
	if len(forward) != 1:
		return None
	return forward[0].parent, forward[0].name


def link_credit_note_to_original_invoice(doc, method=None):
	"""Set `return_against` on a credit note ERPNext mapped from a stock return.

	Without this the note is standalone: the invoice it reverses stays **Unpaid**
	and the two never appear in each other's Connections. See
	:data:`CREDIT_NOTE_BACKLINK` for the measurement.

	Deliberately all-or-nothing. `return_against` alone is worse than nothing —
	ERPNext's over-return guard (`validate_returned_items`) keys on the ROW link,
	and with that blank it degrades from an error to a msgprint, so a second full
	return would save. Either every row resolves to the same original invoice and
	both links are written, or the note is left standalone exactly as before.
	"""
	config = CREDIT_NOTE_BACKLINK.get(doc.doctype)
	if not config or not cint(doc.get("is_return")) or doc.get("return_against"):
		return
	if not doc.get("items"):
		return
	config = dict(config, _doctype=doc.doctype)

	resolved = []
	for row in doc.items:
		found = _original_invoice_row_for(row, config)
		if not found:
			return
		resolved.append(found)

	invoices = {invoice for invoice, _ in resolved}
	if len(invoices) != 1:
		return
	invoice = invoices.pop()

	# ERPNext throws if the party or company differ, so a mismatch must leave the
	# note standalone rather than turn a working save into a hard error.
	original = frappe.db.get_value(
		doc.doctype, invoice, [config["party_field"], "company"], as_dict=True
	)
	if not original:
		return
	if cstr(original.get(config["party_field"])) != cstr(doc.get(config["party_field"])):
		return
	if cstr(original.company) != cstr(doc.get("company")):
		return

	doc.return_against = invoice
	for row, (_, invoice_row) in zip(doc.items, resolved):
		row.set(config["row_link"], invoice_row)


#: The two doctypes carrying `update_outstanding_for_self`.
SETTLE_AGAINST_ORIGINAL_DOCTYPES = ("Sales Invoice", "Purchase Invoice")


def setup_credit_note_settles_original():
	"""Make a linked credit note reduce the ORIGINAL invoice, not just itself.

	🔴 `return_against` alone does NOT settle anything. ERPNext ships
	`update_outstanding_for_self` with **default "1"**, and at
	`accounts_controller.py:213` a return that has it set keeps its own outstanding
	and merely msgprints *"…uncheck the 'Update Outstanding for Self' checkbox"*.
	So the original invoice stays **Unpaid** even when the link is perfect — which
	is exactly what the client reported on KSIN-26-0610 / KSSR-26-0031, and why
	linking them was only half the fix.

	Flipping the DEFAULT (rather than forcing the value in a hook) is deliberate:
	the checkbox stays visible and a user can still tick it back per document, and
	ERPNext keeps its own safety valve — `accounts_controller.py:222` re-sets the
	flag to 1 by itself when the credit exceeds the original's outstanding, so an
	over-credit can never be forced onto an invoice that cannot absorb it.

	POLICY: this makes a credit note settle the invoice it reverses. The alternative
	is ERPNext's default — both documents stay open and are matched later with the
	Payment Reconciliation tool. Flip the value here to go back to that.
	"""
	applied, already, failed = 0, 0, []

	for doctype in SETTLE_AGAINST_ORIGINAL_DOCTYPES:
		if not frappe.get_meta(doctype).get_field("update_outstanding_for_self"):
			failed.append(f"{doctype}: no update_outstanding_for_self field")
			continue

		existing = frappe.db.get_value(
			"Property Setter",
			{
				"doc_type": doctype,
				"field_name": "update_outstanding_for_self",
				"property": "default",
			},
			["name", "value"],
			as_dict=True,
		)
		if existing:
			if cstr(existing.value) != "0":
				frappe.db.set_value("Property Setter", existing.name, "value", "0")
				applied += 1
			else:
				already += 1
			continue

		try:
			frappe.make_property_setter(
				{
					"doctype": doctype,
					"fieldname": "update_outstanding_for_self",
					"property": "default",
					"value": "0",
					"property_type": "Text",
				},
				is_system_generated=True,
			)
			applied += 1
		except Exception as e:
			failed.append(f"{doctype}: {type(e).__name__}: {e}")

	return {"applied": applied, "already": already, "failed": failed}
