# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Price Assist — what should I charge for this item?

MoM §2.5 asks for the last rate sold to this customer and live stock on the item
line. This answers the whole question in one call so the salesman is not guessing
or opening three reports:

* the price list rate that ERPNext will apply
* the last rate sold to **this** customer, and when
* the last rate sold to **anyone**, and to whom
* the highest and lowest rate in the recent window, so an outlier is visible
* current stock in the user's own branch warehouses
* valuation, and therefore the margin the proposed rate would earn

Every query is scoped by the caller's branch warehouses, so a branch user sees
their own trading history and not another branch's pricing.

Existing implementations elsewhere in the estate (`sf_trading.last_selling_rate`,
the `last_purchase_rate` app) each answer a slice of this by scraping the grid
toolbar in JS. This is deliberately server-side: one round trip, permission
filters applied in SQL, and no dependence on frappe's grid DOM.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

#: How far back "recent" reaches for the high/low band and the history list.
DEFAULT_LIMIT = 15


def _branch_warehouses(user=None) -> list[str]:
	"""The caller's branch warehouses, or [] meaning unrestricted."""
	from yht_custom.branch_filters import get_branch_warehouses

	return get_branch_warehouses(user or frappe.session.user)


def _company(company=None) -> str | None:
	return company or frappe.defaults.get_user_default("company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)


@frappe.whitelist()
def get_price_assist(item_code: str, customer: str | None = None, company: str | None = None,
                     price_list: str | None = None, qty: float = 1) -> dict:
	"""Everything needed to price one line. Read-only."""
	if not item_code:
		frappe.throw(_("Item Code is required"))

	# A public endpoint: prove the caller may read the item and the history behind it.
	frappe.has_permission("Item", "read", throw=True)
	frappe.has_permission("Sales Invoice", "read", throw=True)

	company = _company(company)
	warehouses = _branch_warehouses()

	item = frappe.db.get_value(
		"Item", item_code,
		["item_name", "stock_uom", "is_stock_item", "last_purchase_rate"],
		as_dict=True,
	)
	if not item:
		frappe.throw(_("Item {0} not found").format(item_code))

	out = {
		"item_code": item_code,
		"item_name": item.item_name,
		"stock_uom": item.stock_uom,
		"currency": frappe.db.get_value("Company", company, "default_currency") if company else None,
		"price_list": price_list or frappe.db.get_single_value("Selling Settings", "selling_price_list"),
		"restricted_to_warehouses": warehouses,
	}

	out["price_list_rate"] = _price_list_rate(item_code, out["price_list"])
	out["last_to_this_customer"] = _last_sale(item_code, company, warehouses, customer=customer)
	out["last_to_anyone"] = _last_sale(item_code, company, warehouses)
	out["band"] = _rate_band(item_code, company, warehouses)
	out["stock"] = _stock(item_code, warehouses) if item.is_stock_item else []
	# Valuation drives the margin hint. last_purchase_rate is a fallback for a
	# non-stock or never-received item, where there is no valuation to read.
	out["valuation_rate"] = _valuation(item_code, warehouses) or flt(item.last_purchase_rate)
	out["qty"] = flt(qty) or 1
	return out


def _price_list_rate(item_code, price_list):
	if not price_list:
		return None
	return frappe.db.get_value(
		"Item Price",
		{"item_code": item_code, "price_list": price_list, "selling": 1},
		"price_list_rate",
	) or frappe.db.get_value(
		"Item Price", {"item_code": item_code, "price_list": price_list}, "price_list_rate"
	)


def _sale_conditions(warehouses, customer=None):
	"""Shared WHERE for the sales-history queries. Parameterised throughout."""
	where = ["si.docstatus = 1", "sii.item_code = %(item_code)s"]
	params = {}
	if customer:
		where.append("si.customer = %(customer)s")
		params["customer"] = customer
	if warehouses:
		# Branch scope: the item row's warehouse, or the header's when the row is blank.
		where.append(
			"(sii.warehouse IN %(warehouses)s"
			" OR (IFNULL(sii.warehouse, '') = '' AND si.set_warehouse IN %(warehouses)s))"
		)
		params["warehouses"] = warehouses
	return where, params


def _last_sale(item_code, company, warehouses, customer=None):
	where, params = _sale_conditions(warehouses, customer)
	if company:
		where.append("si.company = %(company)s")
		params["company"] = company
	params["item_code"] = item_code

	rows = frappe.db.sql(
		f"""
		SELECT si.name AS invoice, si.posting_date, si.customer, si.customer_name,
		       sii.rate, sii.qty, sii.uom, sii.discount_percentage, si.currency
		FROM `tabSales Invoice Item` sii
		INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE {' AND '.join(where)}
		ORDER BY si.posting_date DESC, si.creation DESC
		LIMIT 1
		""",
		params,
		as_dict=True,
	)
	return rows[0] if rows else None


def _rate_band(item_code, company, warehouses, limit=DEFAULT_LIMIT):
	"""High / low / average over the recent window, so an outlier rate is obvious."""
	where, params = _sale_conditions(warehouses)
	if company:
		where.append("si.company = %(company)s")
		params["company"] = company
	params.update({"item_code": item_code, "limit": cint(limit)})

	rows = frappe.db.sql(
		f"""
		SELECT sii.rate FROM `tabSales Invoice Item` sii
		INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE {' AND '.join(where)} AND sii.rate > 0
		ORDER BY si.posting_date DESC, si.creation DESC
		LIMIT %(limit)s
		""",
		params,
	)
	rates = [flt(r[0]) for r in rows]
	if not rates:
		return None
	return {
		"low": min(rates),
		"high": max(rates),
		"avg": sum(rates) / len(rates),
		"samples": len(rates),
	}


def _stock(item_code, warehouses):
	filters = {"item_code": item_code, "actual_qty": ["!=", 0]}
	if warehouses:
		filters["warehouse"] = ["in", warehouses]
	return frappe.get_all(
		"Bin",
		filters=filters,
		fields=["warehouse", "actual_qty", "reserved_qty", "projected_qty", "valuation_rate"],
		order_by="actual_qty desc",
	)


def _valuation(item_code, warehouses):
	filters = {"item_code": item_code, "actual_qty": [">", 0]}
	if warehouses:
		filters["warehouse"] = ["in", warehouses]
	rows = frappe.get_all("Bin", filters=filters, fields=["stock_value", "actual_qty"])
	total_qty = sum(flt(r.actual_qty) for r in rows)
	if not total_qty:
		return None
	return sum(flt(r.stock_value) for r in rows) / total_qty


@frappe.whitelist()
def get_price_history(
	item_code: str,
	customer: str | None = None,
	company: str | None = None,
	limit: int = 30,
) -> dict:
	"""Recent sales of this item PLUS the buying and stock position.

	Returns ``{"rows": [...], "summary": {...}}``.

	The shape changed from a bare list on purpose: an operator asking "what has this sold for"
	almost always also wants "what did we pay for it" and "have we got any", and making them
	close the dialog and open Price Assist to find out was two clicks for one question.
	"""
	if not item_code:
		frappe.throw(_("Item Code is required"))
	frappe.has_permission("Sales Invoice", "read", throw=True)

	company = _company(company)
	warehouses = _branch_warehouses()
	where, params = _sale_conditions(warehouses, customer)
	if company:
		where.append("si.company = %(company)s")
		params["company"] = company
	params.update({"item_code": item_code, "limit": cint(limit) or 30})

	rows = frappe.db.sql(
		f"""
		SELECT si.name AS invoice, si.posting_date, si.customer, si.customer_name,
		       sii.qty, sii.uom, sii.rate, sii.discount_percentage, sii.amount,
		       sii.warehouse, si.currency
		FROM `tabSales Invoice Item` sii
		INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE {' AND '.join(where)}
		ORDER BY si.posting_date DESC, si.creation DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)

	return {"rows": rows, "summary": _buying_and_stock(item_code, company, warehouses)}


def _purchase_conditions(warehouses, supplier=None):
	"""Shared WHERE for the purchase-history query. Parameterised throughout.

	Deliberately the same shape as `_sale_conditions`: scope on the item row's warehouse,
	falling back to the header's when the row is blank. That is TIGHTER than
	`branch_filters.purchase_invoice_query`, which also lets a branch see a document its own
	peers created regardless of warehouse — right for a list view, wrong here. "What did we
	pay" on a pricing dialog means what THIS branch paid into its own warehouses, which is
	the same basis as the sales figures sitting directly above it.
	"""
	where = ["pi.docstatus = 1", "pii.item_code = %(item_code)s"]
	params = {}
	if supplier:
		where.append("pi.supplier = %(supplier)s")
		params["supplier"] = supplier
	if warehouses:
		where.append(
			"(pii.warehouse IN %(warehouses)s"
			" OR (IFNULL(pii.warehouse, '') = '' AND pi.set_warehouse IN %(warehouses)s))"
		)
		params["warehouses"] = warehouses
	return where, params


@frappe.whitelist()
def get_purchase_history(
	item_code: str,
	supplier: str | None = None,
	company: str | None = None,
	limit: int = 30,
) -> dict:
	"""Recent PURCHASES of this item — the buying counterpart of `get_price_history`.

	Returns ``{"rows": [...]}``. No summary: the buying and stock figures already sit in
	`get_price_history`'s summary and in the Price Assist body, and duplicating them here
	would give the operator two places to read one number.

	`rate` is the purchase rate in the invoice's own currency. `base_rate` comes along so a
	foreign-currency purchase can be compared with the company-currency valuation shown
	beside it — without it, a USD invoice reads as though we paid three times less than we
	did.
	"""
	if not item_code:
		frappe.throw(_("Item Code is required"))
	# Gate on Purchase Invoice, NOT Sales Invoice. Branch User holds both reads
	# (`setup.BRANCH_USER_PERMISSIONS`), but a role that can sell without seeing cost must
	# get a clean permission error rather than a table of supplier prices.
	frappe.has_permission("Purchase Invoice", "read", throw=True)

	company = _company(company)
	warehouses = _branch_warehouses()
	where, params = _purchase_conditions(warehouses, supplier)
	if company:
		where.append("pi.company = %(company)s")
		params["company"] = company
	params.update({"item_code": item_code, "limit": cint(limit) or 30})

	rows = frappe.db.sql(
		f"""
		SELECT pi.name AS invoice, pi.posting_date, pi.supplier, pi.supplier_name,
		       pi.bill_no, pi.currency,
		       pii.qty, pii.uom, pii.stock_qty, pii.stock_uom, pii.rate, pii.base_rate,
		       pii.discount_percentage, pii.amount, pii.warehouse
		FROM `tabPurchase Invoice Item` pii
		INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
		WHERE {' AND '.join(where)}
		ORDER BY pi.posting_date DESC, pi.creation DESC
		LIMIT %(limit)s
		""",
		params,
		as_dict=True,
	)

	return {"rows": rows}


def _buying_and_stock(item_code: str, company: str | None, warehouses: list) -> dict:
	"""What we paid, what the buying list says, and what is on the shelf.

	`last_purchase_rate` on the Item is a single stale number with no date attached, so the
	last purchase comes from ERPNext's own `get_last_purchase_details`, which walks Purchase
	Order, Purchase Receipt and Purchase Invoice and returns the most recent in STOCK UOM —
	the same basis as the valuation, so the two figures are comparable.
	"""
	from erpnext.stock.doctype.item.item import get_last_purchase_details

	item = frappe.db.get_value(
		"Item", item_code, ["item_name", "stock_uom", "is_stock_item", "last_purchase_rate"], as_dict=True
	) or frappe._dict()

	try:
		last = get_last_purchase_details(item_code) or frappe._dict()
	except Exception:
		# Never let a reporting extra break the dialog the operator is waiting on.
		frappe.log_error(frappe.get_traceback(), "yht price history: last purchase")
		last = frappe._dict()

	buying_list = frappe.db.get_single_value("Buying Settings", "buying_price_list")
	buying_rate = None
	if buying_list:
		buying_rate = frappe.db.get_value(
			"Item Price",
			{"item_code": item_code, "price_list": buying_list, "selling": 0},
			"price_list_rate",
		)

	stock = _stock(item_code, warehouses)
	return {
		"item_name": item.get("item_name"),
		"stock_uom": item.get("stock_uom"),
		"is_stock_item": cint(item.get("is_stock_item")),
		"last_purchase_rate": flt(last.get("rate")) or flt(item.get("last_purchase_rate")) or None,
		"last_purchase_date": last.get("purchase_date"),
		"buying_price_list": buying_list,
		"buying_price_list_rate": flt(buying_rate) if buying_rate else None,
		"valuation_rate": _valuation(item_code, warehouses),
		"available_qty": sum(flt(row.get("actual_qty")) for row in stock),
		"reserved_qty": sum(flt(row.get("reserved_qty")) for row in stock),
		"stock": stock,
	}
