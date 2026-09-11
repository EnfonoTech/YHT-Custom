# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Sales and purchase flow policy.

MoM §2.2 and the client's own module sheet settle three things that the legacy
site left to each user's discretion:

* **Stock is not moved twice.** `update_stock` is switched off when — and only
  when — the goods on the document have already moved on a stock document.

  🔴 THIS REVERSES "Delivery Note is compulsory" (MoM §2.2), which forced
  `update_stock = 0` for every non-bypass user until 2026-09-10. Client sheet
  item 25 asks for a standalone invoice to open TICKED for branch users too, and
  the gate approved it (Q1) on the second asking. What is given up, stated: on
  the legacy site 1,339 of 2,337 submitted invoices came through a Delivery Note
  and 998 updated stock directly, and the DN-compulsory rule existed to end that
  split. A branch user can again bill and ship in one document. The *scope*
  boundary is untouched — `branch_guard.validate_branch_scope` still rejects a
  warehouse outside the branch — what changed is the flow policy.
* **A zero-rate Delivery Note is blocked.** Goods must not leave at nil value.
* **A submitted Delivery Note is locked**, so the printed copy the driver carries
  always matches the record.
* **Purchase stock arrives on the Purchase Receipt**, not on the Purchase Invoice.

The measured reason this matters: of 2,337 submitted invoices on the legacy site,
1,339 came through a Delivery Note and 998 updated stock directly. Same business,
two incompatible habits, and no way to reconcile a delivery against an invoice.
"""

import frappe
from frappe import _
from frappe.model import display_fieldtypes, table_fields
from frappe.utils import cint, cstr, flt

from yht_custom import branch_defaults, other_remarks

#: Roles that may still tick `update_stock` on a Sales Invoice, i.e. bill and
#: ship in one document. Everyone else goes through a Delivery Note.
#:
#: ⚠️ THESE NO LONGER DECIDE `update_stock` (client sheet item 25, gate Q1).
#: `lock_submitted_delivery_note` and the Delivery Note refresh comment still
#: read them, which is why they are kept.
DIRECT_STOCK_ROLES = (
	"System Manager",
	"Stock Manager",
	"Sales Manager",
	"Sales Master Manager",
	"Accounts Manager",
)

#: Ceiling on `sales_order_has_stock_document`'s caller-supplied row list.
#:
#: The endpoint answers an existence question about row names it does not
#: permission-check individually, so the list it will accept is bounded to keep
#: the leak at "one bit per guessed name" rather than "walk the table".
#: Measured on `yht-test` 2026-09-10: the largest document in the site's history
#: is 169 Sales Invoice rows, 70 Sales Order rows, 54 Purchase Invoice rows. 500
#: leaves generous headroom over all three and still refuses a scripted probe.
MAX_PROBED_ROWS = 500

#: Client sheet item 25 — how each invoice reaches the stock document behind it.
#:
#: `row_link` is the child field ERPNext writes when the goods have ALREADY moved
#: on a stock document; `order_link` is the row's link back to the order, and
#: `stock_order_link` is that same order row seen from the stock document's side.
#: The two sides are NOT symmetric — `Delivery Note Item.so_detail` against
#: `Purchase Receipt Item.purchase_order_item` — so both are named rather than
#: derived, and every one was read off live meta before it was written here.
_STOCK_ROUTE = {
	"Sales Invoice": {
		"row_link": "dn_detail",
		"order_link": "so_detail",
		"stock_parent": "Delivery Note",
		"stock_child": "Delivery Note Item",
		"stock_order_link": "so_detail",
	},
	"Purchase Invoice": {
		"row_link": "pr_detail",
		"order_link": "po_detail",
		"stock_parent": "Purchase Receipt",
		"stock_child": "Purchase Receipt Item",
		"stock_order_link": "purchase_order_item",
	},
}


def _may_bypass(user=None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(frappe.get_roles(user)) & set(DIRECT_STOCK_ROLES))


def _stock_document_against(doctype: str, order_rows) -> str | None:
	"""The stock document already covering any of these order rows, or None.

	ONE query however many rows the document carries. An N+1 here would run on
	every save of every invoice, and a twenty-line invoice is ordinary.
	"""
	spec = _STOCK_ROUTE.get(doctype)
	if not spec or not order_rows:
		return None

	child = frappe.qb.DocType(spec["stock_child"])
	parent = frappe.qb.DocType(spec["stock_parent"])
	found = (
		frappe.qb.from_(child)
		.join(parent)
		.on(parent.name == child.parent)
		.select(parent.name)
		.where(
			# 🔴 SUBSCRIPT, NEVER `.field(...)`. `frappe/query_builder/__init__.py:23`
			# monkey-patches pypika with `Selectable.field = PseudoColumn("field")` — an
			# INSTANCE, not the method pypika ships. `child.field` therefore never reaches
			# the `__getattr__` on line 21 (it is a real class attribute) and calling it
			# raises `TypeError: 'PseudoColumn' object is not callable`. Line 22 patches
			# `__getitem__` to build the `Field` directly, which is why this form works and
			# is the only form used anywhere in frappe, erpnext or this app.
			child[spec["stock_order_link"]].isin(list(order_rows))
			& (parent.docstatus == 1)
			& (parent.is_return == 0)
		)
		.limit(1)
	).run()
	return found[0][0] if found else None


def _stock_already_moved(doc) -> str | None:
	"""Item 25's linkage rule. Zeroes `update_stock`; names the document if visible.

	🔴 THIS REPLACED A ROLE TEST, AND THAT IS THE WHOLE ITEM (gate Q1). Until now
	`update_stock` was forced to 0 for every non-bypass user, which is the MoM
	§2.2 "Delivery Note is compulsory" policy. The client has asked twice for a
	standalone invoice to open TICKED for branch users too, so the question the
	rule asks is no longer *who is keying this in* but *have these goods already
	moved*:

	1. a row carrying the stock-document link → 0, and return None, because
	   ERPNext's own `depends_on` HIDES the box in that state: there is nothing
	   for the operator to reconcile and a message would only confuse.
	2. otherwise, an order row behind this document that a submitted, non-return
	   stock document already covers → 0, and return that document's name so the
	   caller can say so. Here the field IS visible and the flip needs explaining.
	3. otherwise leave the value alone, the new default included.

	Step 1 is not cosmetic. `get_mapped_doc` copies field defaults onto the
	target, so without it every invoice mapped from a Delivery Note would arrive
	with `update_stock = 1` and `SalesInvoice.validate_delivery_note()` would
	refuse the save with an error the operator cannot act on — the field being
	hidden. The purchase side has no equivalent throw at all, so the stock would
	simply be received a second time, silently.
	"""
	spec = _STOCK_ROUTE[doc.doctype]
	rows = doc.get("items") or []

	if any(cstr(row.get(spec["row_link"])).strip() for row in rows):
		doc.update_stock = 0
		return None

	order_rows = {
		cstr(row.get(spec["order_link"])).strip()
		for row in rows
		if cstr(row.get(spec["order_link"])).strip()
	}
	stock_document = _stock_document_against(doc.doctype, order_rows)
	if not stock_document:
		return None

	doc.update_stock = 0
	return stock_document


# ------------------------------------------------------------- Sales Invoice


def enforce_delivery_note_route(doc, method=None):
	"""Switch `update_stock` off when the goods have already gone out on a note.

	Server-side rather than JS-only: the form lock stops the ordinary user, this
	stops a REST call, an import and a Server Script as well. See
	`_stock_already_moved` for the rule and for what it replaced.

	🔴 A RETURN IS NOT A SALE, and this had no `is_return` branch until 2026-08-26.
	How the goods LEFT decides how they come back, so `update_stock` on a return is
	dictated by the original document, not by this rule — ERPNext itself throws
	when a return ticks it and its original did not. Zeroing it unconditionally
	meant a branch user returning a legacy direct-stock invoice could never bring
	the goods back at all (measured: `is_return=1, update_stock=1` in, `0` out).
	`return_flow.enforce_return_stock_route` owns the return case.
	"""
	if cint(doc.get("is_return")):
		return
	if not cint(doc.get("update_stock")):
		return

	note = _stock_already_moved(doc)
	if not note:
		return

	frappe.msgprint(
		_(
			"These goods are already going out on Delivery Note {0}, so <b>Update Stock</b> has been switched off on this invoice."
		).format(note),
		title=_("Already Delivered"),
		indicator="orange",
	)


# -------------------------------------------------------------- Delivery Note


def validate_delivery_note(doc, method=None):
	"""Block a nil-value delivery, and keep a submitted DN immutable."""
	_block_zero_rate(doc)


def _block_zero_rate(doc):
	"""Goods must not leave the warehouse at zero value.

	A free-of-charge delivery is a real thing, but it belongs on a document that
	says so — not as a silent zero on an ordinary DN, which is how stock walks out
	unaccounted.
	"""
	if cint(doc.get("is_return")):
		return  # a return legitimately mirrors the original, including nil lines

	offenders = [row.idx for row in (doc.get("items") or []) if flt(row.get("rate")) <= 0]
	if not offenders:
		return

	frappe.throw(
		_("Rows {0} have a zero rate. A Delivery Note cannot release goods at nil value.").format(
			", ".join(str(i) for i in offenders)
		),
		title=_("Zero Rate Not Allowed"),
	)


def _comparable(doc, field):
	"""One field's value, in a shape two copies of the same document can compare.

	🔴 A CHILD TABLE COMPARED DIRECTLY IS ALWAYS "CHANGED", AND THAT MADE THE LOCK
	ABSOLUTE. `doc.get("items")` and `before.get("items")` are two different lists
	holding two different child `Document` objects, and frappe's `BaseDocument`
	defines no `__eq__` — so `!=` falls back to identity and EVERY Table field
	reports a change on every save. `lock_submitted_delivery_note` therefore threw
	for any post-submit edit by a non-bypass user whatever actually changed
	(measured: `Changed: items, sales_team, taxes` on a save that touched only
	`custom_other_remarks`), which is what made item 28's exemption inert on the
	one doctype the client most wants the field on.

	A per-row dict compares by VALUE. `no_default_fields` drops `modified` /
	`modified_by` / `idx` churn that is not an operator edit, and
	`no_private_properties` drops `__unsaved` / `__islocal`, which are set on the
	in-memory copy and absent from the one loaded out of the database — on their
	own enough to make every row differ again.
	"""
	if field.fieldtype in table_fields:
		return [
			row.as_dict(no_default_fields=True, no_private_properties=True)
			for row in (doc.get(field.fieldname) or [])
		]
	return doc.get(field.fieldname)


def lock_submitted_delivery_note(doc, method=None):
	"""Refuse post-submit edits to a Delivery Note.

	ERPNext allows `allow_on_submit` fields to change after submit. On a document
	the driver has already carried out of the yard, that means the printed copy
	and the record can silently diverge.
	"""
	if doc.docstatus != 1:
		return
	before = doc.get_doc_before_save()
	if not before:
		return

	# Fields ERPNext or our own automation legitimately writes after submit.
	#
	# 🔴 `other_remarks.FIELDNAME` IS THE EXEMPTION THIS LOCK EXISTS TO GRANT.
	# Client sheet item 28 makes "Other Remarks" `allow_on_submit` precisely so a
	# note can be added to a document that has already gone out. Without it here
	# the lock refuses that edit for every non-bypass user — which is exactly who
	# the field is for, and Delivery Note is the doctype the client most wants it
	# on. Read from the module rather than retyped: a second spelling of a
	# fieldname is how an exemption quietly stops matching.
	permitted = {
		"status", "per_billed", "per_returned", "billing_status",
		"modified", "modified_by", "_user_tags", "_comments", "_assign", "_liked_by",
		"docstatus", "workflow_state",
		other_remarks.FIELDNAME,
	}
	changed = {
		field.fieldname
		for field in doc.meta.fields
		if field.fieldtype not in display_fieldtypes
		and field.fieldname not in permitted
		and _comparable(doc, field) != _comparable(before, field)
	}
	if not changed:
		return
	if _may_bypass():
		return

	frappe.throw(
		_("A submitted Delivery Note cannot be edited. Changed: {0}").format(", ".join(sorted(changed))),
		title=_("Delivery Note Locked"),
	)


# ------------------------------------------------------------ Purchase Invoice


def enforce_purchase_receipt_route(doc, method=None):
	"""Switch `update_stock` off when the goods have already been received.

	Expense invoices are exempt: they carry no stock at all, and
	`expense_invoice.before_validate` zeroes the flag for them in any case.

	A buyer's wording, not a seller's: this handler and its Sales Invoice twin
	share a rule but not a sentence — an instruction naming a Delivery Note is
	one a purchasing clerk cannot follow.

	🔴 A RETURN IS NOT A SALE, and this had no `is_return` branch until 2026-08-26.
	How the goods LEFT decides how they come back, so `update_stock` on a return is
	dictated by the original document, not by this rule — ERPNext itself throws
	when a return ticks it and its original did not. Zeroing it unconditionally
	meant a branch user returning a legacy direct-stock bill could never bring
	the goods back at all (measured: `is_return=1, update_stock=1` in, `0` out).
	`return_flow.enforce_return_stock_route` owns the return case.
	"""
	if cint(doc.get("is_return")):
		return
	if cint(doc.get("custom_is_expense_invoice")):
		return
	if not cint(doc.get("update_stock")):
		return

	receipt = _stock_already_moved(doc)
	if not receipt:
		return

	frappe.msgprint(
		_(
			"These goods are already arriving on Purchase Receipt {0}, so <b>Update Stock</b> has been switched off on this bill."
		).format(receipt),
		title=_("Already Received"),
		indicator="orange",
	)


# ------------------------------------------------------------------ whitelisted


@frappe.whitelist()
def may_use_direct_stock() -> bool:
	"""Whether the current user holds a bypass role.

	No longer decides `update_stock` (item 25) — it still drives the Delivery
	Note refresh comment, and `lock_submitted_delivery_note` reads the same
	answer.
	"""
	return _may_bypass()


@frappe.whitelist()
def sales_order_has_stock_document(doctype: str = "Sales Invoice", details=None) -> bool:
	"""Have any of these order rows already moved on a stock document?

	The second half of item 25's form lock: a row's own `dn_detail` / `pr_detail`
	is visible to the client, but "does the Sales Order behind this line already
	have a Delivery Note" is a question only the server can answer.

	A public HTTP endpoint, so be exact about what is and is not checked.

	CHECKED: read permission on `doctype` — the INVOICE doctype the form is on,
	which is what gates reaching this endpoint at all.

	NOT CHECKED: the caller-supplied `details`. Those are Sales Order Item row
	names, probed against `Delivery Note Item` / `Purchase Receipt Item` with no
	branch filter and no `permission_query_conditions` — a report bypasses those
	too (gotcha 20), and a row-level check here would be a second query per row
	on every form refresh. What that costs is bounded deliberately: the answer is
	a single boolean, never a document name, and `details` is capped at
	MAX_PROBED_ROWS so the endpoint cannot be walked as a bulk oracle. The
	exposure is therefore one bit per correctly guessed row name — a row name is
	a `hash` autoname, not a series — for a caller who already holds read on the
	invoice doctype.
	"""
	doctype = cstr(doctype)
	frappe.has_permission(doctype, "read", throw=True)

	if isinstance(details, str):
		details = frappe.parse_json(details)
	order_rows = {cstr(row).strip() for row in (details or []) if cstr(row).strip()}
	if len(order_rows) > MAX_PROBED_ROWS:
		# A real form sends one name per line. Anything past that is not a form.
		frappe.throw(
			_("Too many rows to check at once ({0}).").format(len(order_rows)),
			frappe.ValidationError,
		)

	return bool(_stock_document_against(doctype, order_rows))


# --------------------------------------------------- Get Items From > Sales Order
#
# 🔴 UPSTREAM SIGNATURE CLASH. `frappe.model.mapper.map_docs` — what the desk's
# "Get Items From" dialog posts to — passes the dialog's `args` POSITIONALLY into
# slot three:
#
#     _args = (src, target_doc, json.loads(args)) if args else (src, target_doc)
#
# and the two ERPNext mappers disagree about what slot three is (v15.119.2):
#
#     delivery_note.make_sales_invoice(source_name, target_doc=None, args=None)
#     sales_order.make_sales_invoice(source_name, target_doc=None,
#                                    ignore_permissions=False, args=None)
#
# So Delivery Note works and Sales Order does not: the dialog's payload lands on
# `ignore_permissions`, frappe's pydantic argument validation rejects a dict for
# `Union[int, bool, float]`, and the request 417s. The desk swallows it — the
# dialog closes and the invoice is simply left with no items, which is what
# "Get items from SO to Invoice not working" looks like from the outside.
#
# `map_docs` resolves `frappe.override_whitelisted_method` BEFORE calling, so a
# hook override is honoured. This shim decides by TYPE rather than by position, so
# it stays correct for both callers: the desk (a dict/JSON object in slot three)
# and any code that passes `ignore_permissions` positionally, as ERPNext's own
# signature invites.


@frappe.whitelist()
def make_sales_invoice_from_sales_order(source_name, target_doc=None, third=None, fourth=None):
	"""ERPNext's Sales Order -> Sales Invoice mapper, callable the way the desk calls it."""
	from erpnext.selling.doctype.sales_order.sales_order import (
		make_sales_invoice as erpnext_make_sales_invoice,
	)

	def _looks_like_args(value):
		if isinstance(value, dict):
			return True
		# `map_docs` json-decodes before calling, but a direct HTTP caller may not.
		return isinstance(value, str) and value.strip().startswith("{")

	if _looks_like_args(third):
		args, ignore_permissions = third, fourth
	else:
		ignore_permissions, args = third, fourth

	return erpnext_make_sales_invoice(
		source_name,
		target_doc,
		ignore_permissions=cint(ignore_permissions),
		args=args,
	)


@frappe.whitelist()
def return_naming_series(doctype: str = "Sales Invoice") -> str | None:
	"""The series a RETURN of ``doctype`` will take, for the calling user's branch.

	``None`` means "leave the picker alone": the branch configures no return series
	for this doctype, or the series could not be resolved at all — several branches
	exist and this caller is pinned to none of them. A bypass role is NOT on its own
	enough to return ``None`` any more: on a single-branch site the series falls back
	to that branch for everybody, because a credit note must not take the invoice
	counter whoever keys it in. See ``branch_defaults._branch_series_rows``.

	The entry point calls this so the form shows the series it will actually get.
	Without it the picker keeps the form's pre-filled ``KSIN-`` after ``is_return`` is
	ticked and the document saves as ``KSSR-``, which reads as a bug.
	"""
	doctype = cstr(doctype)
	frappe.has_permission(doctype, "create", throw=True)
	return branch_defaults.configured_series(doctype, is_return=1)
