# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Sales and purchase flow policy.

MoM §2.2 and the client's own module sheet settle three things that the legacy
site left to each user's discretion:

* **Delivery Note is compulsory** at go-live. Stock leaves on the DN; the Sales
  Invoice bills it. The direct `update_stock` route stays available to managers,
  and the policy is reviewed after roughly a month.
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
from frappe.utils import cint, cstr, flt

from yht_custom import branch_defaults

#: Roles that may still tick `update_stock` on a Sales Invoice, i.e. bill and
#: ship in one document. Everyone else goes through a Delivery Note.
DIRECT_STOCK_ROLES = (
	"System Manager",
	"Stock Manager",
	"Sales Manager",
	"Sales Master Manager",
	"Accounts Manager",
)


def _may_bypass(user=None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(frappe.get_roles(user)) & set(DIRECT_STOCK_ROLES))


# ------------------------------------------------------------- Sales Invoice


def enforce_delivery_note_route(doc, method=None):
	"""Force `update_stock = 0` for users without a bypass role.

	Server-side rather than JS-only: the form lock stops the ordinary user, this
	stops a REST call, an import and a Server Script as well.

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
	if _may_bypass():
		return
	if not cint(doc.get("update_stock")):
		return

	doc.update_stock = 0
	frappe.msgprint(
		_("Stock is delivered on a Delivery Note, so <b>Update Stock</b> has been switched off on this invoice."),
		title=_("Delivery Note Required"),
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
	permitted = {
		"status", "per_billed", "per_returned", "billing_status",
		"modified", "modified_by", "_user_tags", "_comments", "_assign", "_liked_by",
		"docstatus", "workflow_state",
	}
	changed = {
		field.fieldname
		for field in doc.meta.fields
		if field.fieldname not in permitted and doc.get(field.fieldname) != before.get(field.fieldname)
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
	"""Stock arrives on the Purchase Receipt, per the client's module sheet.

	Expense invoices are exempt: they carry no stock at all.

	🔴 A RETURN IS NOT A SALE, and this had no `is_return` branch until 2026-08-26.
	How the goods LEFT decides how they come back, so `update_stock` on a return is
	dictated by the original document, not by this rule — ERPNext itself throws
	when a return ticks it and its original did not. Zeroing it unconditionally
	meant a branch user returning a legacy direct-stock bill could never bring
	the goods back at all (measured: `is_return=1, update_stock=1` in, `0` out).
	`return_flow.enforce_return_stock_route` owns the return case.
	"""
	if cint(doc.get("custom_is_expense_invoice")):
		return
	if cint(doc.get("is_return")):
		return
	if _may_bypass():
		return
	if not cint(doc.get("update_stock")):
		return

	doc.update_stock = 0
	frappe.msgprint(
		_("Stock is received on a Purchase Receipt, so <b>Update Stock</b> has been switched off on this invoice."),
		title=_("Purchase Receipt Required"),
		indicator="orange",
	)


# ------------------------------------------------------------------ whitelisted


@frappe.whitelist()
def may_use_direct_stock() -> bool:
	"""Whether the current user may tick update_stock. Drives the form lock."""
	return _may_bypass()


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

	``None`` means "leave the picker alone" — the caller holds a bypass role, or the
	branch configures no return series for this doctype.

	The entry point calls this so the form shows the series it will actually get.
	Without it the picker keeps the form's pre-filled ``KSIN-`` after ``is_return`` is
	ticked and the document saves as ``KSCN-``, which reads as a bug.
	"""
	doctype = cstr(doctype)
	frappe.has_permission(doctype, "create", throw=True)
	return branch_defaults.configured_series(doctype, is_return=1)
