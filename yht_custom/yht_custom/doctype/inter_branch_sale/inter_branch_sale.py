# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Inter Branch Sale — stock to another group entity that keeps its own books, at a selling price.

The other group entities (Jeddah, Jubail, Yanbu, Al Badr, Waqt Al Enjaz) are not branches of this site; they
are customers carrying the company's VAT number. A sale to them must not be reported to ZATCA, so it is not
a Sales Invoice. It is one document that posts, on submit and in the same transaction:

* a **Stock Entry** (Material Issue): the stock leaves the warehouse at cost, the debit going to the
  Inter-Branch Clearing account instead of a P&L difference account;
* a **Journal Entry**: Dr Receivable (party = the customer) at the selling price, Cr Clearing at cost, and the
  difference to the Inter-Branch Margin account (a debit if it was sold below cost).

Net effect: receivable at selling price, stock out at cost, margin booked, Clearing nets to zero. The cost is
read back from the Stock Ledger, not from the draft, so the Journal Entry always agrees with the stock value
ERPNext actually posted.

Behind `oct19_inter_branch_sale`, and it cannot be submitted until Inter Branch Sale Settings names every
account (the accounts are the client's accountant's decision, nothing is defaulted). Nothing is sent to ZATCA:
neither a Stock Entry nor a Journal Entry is a ZATCA document.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_link_to_form

from yht_custom import features

FEATURE = "oct19_inter_branch_sale"
SETTINGS = "Inter Branch Sale Settings"


def posting_rows(total_amount: float, total_cost: float) -> list:
	"""The Journal Entry legs as (leg, debit, credit); balanced by construction.

	Pure arithmetic, no database, so the rounding and the sign of the margin are testable on their own.
	"""
	total_amount = flt(total_amount, 2)
	total_cost = flt(total_cost, 2)
	margin = flt(total_amount - total_cost, 2)
	rows = [("receivable", total_amount, 0.0), ("clearing", 0.0, total_cost)]
	if margin > 0:
		rows.append(("margin", 0.0, margin))
	elif margin < 0:
		rows.append(("margin", -margin, 0.0))
	return rows


class InterBranchSale(Document):
	# Frappe refuses to cancel a document while a submitted document links to it. This document links to the
	# two it creates and cancels them itself in `on_cancel`, so those links must not block it.
	ignore_linked_doctypes = ("Stock Entry", "Journal Entry", "GL Entry", "Stock Ledger Entry")

	def validate(self):
		self._require_feature()
		self._apply_defaults()
		self._validate_customer()
		self._set_rates_and_totals()
		self.status = "Draft" if self.docstatus == 0 else self.status

	def _require_feature(self):
		if not features.enabled(FEATURE):
			frappe.throw(_("Inter Branch Sale is not enabled on this site."), title=_("Not Enabled"))

	def _settings(self):
		return frappe.get_cached_doc(SETTINGS)

	def _apply_defaults(self):
		settings = self._settings()
		self.company = self.company or settings.company
		self.cost_center = self.cost_center or settings.cost_center
		self.price_list = self.price_list or settings.get("price_list")
		self.from_warehouse = self.from_warehouse or settings.get("from_warehouse")
		if self.company and settings.company and self.company != settings.company:
			frappe.throw(
				_("Inter Branch Sale is set up for {0}, not {1}.").format(settings.company, self.company),
				title=_("Wrong Company"),
			)

	def _validate_customer(self):
		from yht_custom.yht_custom.doctype.inter_branch_sale_settings.inter_branch_sale_settings import allowed_customers

		if self.customer not in allowed_customers():
			frappe.throw(
				_("{0} is not an inter-branch customer. Add it under Inter Branch Sale Settings first.").format(self.customer),
				title=_("Customer Not Allowed"),
			)

	def _set_rates_and_totals(self):
		if not self.get("items"):
			frappe.throw(_("Add at least one item."), title=_("No Items"))
		total_qty = total_amount = total_cost = 0.0
		for row in self.items:
			if flt(row.qty) <= 0:
				frappe.throw(_("Row {0}: quantity must be more than zero.").format(row.idx))
			row.warehouse = row.warehouse or self.from_warehouse
			if not row.warehouse:
				frappe.throw(_("Row {0}: a source warehouse is required.").format(row.idx))
			row.uom = row.uom or frappe.db.get_value("Item", row.item_code, "stock_uom")
			row.conversion_factor = 1
			row.valuation_rate = get_valuation_rate(row.item_code, row.warehouse)
			if not flt(row.rate) and self.price_list:
				row.rate = get_price_list_rate(row.item_code, self.price_list)
			if not flt(row.rate):
				frappe.throw(
					_("Row {0}: {1} has no selling rate. Type one or add it to the price list.").format(row.idx, row.item_code),
					title=_("No Rate"),
				)
			row.amount = flt(flt(row.qty) * flt(row.rate), 2)
			row.cost_amount = flt(flt(row.qty) * flt(row.valuation_rate), 2)
			total_qty += flt(row.qty)
			total_amount += row.amount
			total_cost += row.cost_amount
		self.total_qty = total_qty
		self.total_amount = flt(total_amount, 2)
		self.total_cost = flt(total_cost, 2)
		self.margin = flt(self.total_amount - self.total_cost, 2)

	# ------------------------------------------------------------------ submit

	def before_submit(self):
		self._require_feature()
		missing = _gaps()
		if missing:
			frappe.throw(
				_("Inter Branch Sale Settings is not complete: {0}.").format(", ".join(_(m) for m in missing)),
				title=_("Setup Incomplete"),
			)
		if not frappe.get_cached_value("Company", self.company, "enable_perpetual_inventory"):
			frappe.throw(
				_("Company {0} does not keep Perpetual Inventory, so the Stock Entry would post no stock ledger "
				  "entries and the receivable would have nothing to offset it.").format(self.company),
				title=_("Perpetual Inventory Required"),
			)
		self._check_stock()

	def _check_stock(self):
		needed = {}
		for row in self.items:
			needed[(row.warehouse, row.item_code)] = needed.get((row.warehouse, row.item_code), 0.0) + flt(row.qty)
		short = []
		for (warehouse, item_code), qty in needed.items():
			have = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))
			if have < qty:
				short.append(f"{item_code} @ {warehouse}: {qty:g} needed, {have:g} available")
		if short:
			frappe.throw("<br>".join(short), title=_("Insufficient Stock"))

	def on_submit(self):
		self.db_set("status", "Submitted")
		stock_entry = self._create_stock_entry()
		self._create_journal_entry(stock_entry)

	def _create_stock_entry(self):
		settings = self._settings()
		se = frappe.new_doc("Stock Entry")
		se.stock_entry_type = "Material Issue"
		se.purpose = "Material Issue"
		se.company = self.company
		se.set_posting_time = 1
		se.posting_date = self.posting_date
		se.posting_time = self.posting_time
		se.remarks = _("Created from {0} {1}").format(_(self.doctype), self.name)
		for row in self.items:
			se.append(
				"items",
				{
					"item_code": row.item_code,
					"qty": row.qty,
					"uom": row.uom,
					"conversion_factor": 1,
					"s_warehouse": row.warehouse,
					"expense_account": settings.clearing_account,
					"cost_center": self.cost_center or settings.cost_center,
				},
			)
		se.flags.ignore_permissions = True
		se.insert(ignore_permissions=True)
		se.submit()
		self.db_set("stock_entry", se.name, notify=True)
		return se

	def _create_journal_entry(self, stock_entry):
		settings = self._settings()
		cost = stock_cost(stock_entry.name)
		if not cost:
			frappe.throw(
				_("The Stock Entry {0} posted no stock value. Give the items a valuation rate in the source warehouse.").format(stock_entry.name),
				title=_("Zero Cost"),
			)
		accounts = {
			"receivable": settings.receivable_account,
			"clearing": settings.clearing_account,
			"margin": settings.margin_account,
		}
		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Journal Entry"
		je.company = self.company
		je.posting_date = self.posting_date
		je.user_remark = _("Inter Branch Sale {0} to {1}").format(self.name, self.customer_name or self.customer)
		for leg, debit, credit in posting_rows(self.total_amount, cost):
			row = {
				"account": accounts[leg],
				"debit_in_account_currency": debit,
				"credit_in_account_currency": credit,
				"cost_center": self.cost_center or settings.cost_center,
			}
			if leg == "receivable":
				row.update({"party_type": "Customer", "party": self.customer})
			je.append("accounts", row)
		je.flags.ignore_permissions = True
		je.insert(ignore_permissions=True)
		je.submit()
		self.db_set({"journal_entry": je.name, "total_cost": cost, "margin": flt(self.total_amount - cost, 2)})
		frappe.msgprint(
			_("Stock Entry {0} and Journal Entry {1} created.").format(
				get_link_to_form("Stock Entry", stock_entry.name), get_link_to_form("Journal Entry", je.name)
			),
			alert=True,
			indicator="green",
		)

	# ------------------------------------------------------------------ cancel

	def on_cancel(self):
		"""Reverse order of creation: the Journal Entry first, then the Stock Entry it accounts for."""
		for doctype, name in (("Journal Entry", self.journal_entry), ("Stock Entry", self.stock_entry)):
			if not name:
				continue
			doc = frappe.get_doc(doctype, name)
			if doc.docstatus == 1:
				doc.flags.ignore_permissions = True
				doc.cancel()
		self.db_set("status", "Cancelled")


def _gaps() -> list:
	from yht_custom.yht_custom.doctype.inter_branch_sale_settings.inter_branch_sale_settings import gaps

	return gaps()


def stock_cost(stock_entry: str) -> float:
	"""What the Stock Entry took out of stock, from the Stock Ledger it actually wrote."""
	rows = frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_type": "Stock Entry", "voucher_no": stock_entry, "is_cancelled": 0},
		fields=["stock_value_difference"],
		limit_page_length=0,
	)
	return flt(-sum(flt(r.stock_value_difference) for r in rows), 2)


def get_valuation_rate(item_code: str, warehouse: str | None) -> float:
	if not item_code:
		return 0.0
	rate = 0.0
	if warehouse:
		rate = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate"))
	return rate or flt(frappe.db.get_value("Item", item_code, "valuation_rate"))


def get_price_list_rate(item_code: str, price_list: str) -> float:
	return flt(
		frappe.db.get_value("Item Price", {"item_code": item_code, "price_list": price_list, "selling": 1}, "price_list_rate")
	)


@frappe.whitelist()
def get_item_rates(item_code: str, warehouse: str | None = None, price_list: str | None = None) -> dict:
	"""Rates for the item grid. Bin, Item Price and Item are often unreadable to branch-scoped roles."""
	frappe.has_permission("Inter Branch Sale", "read", throw=True)
	return {
		"valuation_rate": get_valuation_rate(item_code, warehouse),
		"price_list_rate": get_price_list_rate(item_code, price_list) if price_list else 0.0,
	}


@frappe.whitelist()
def get_inter_branch_customers() -> list:
	"""The customers the sale may use, for the Customer picker."""
	frappe.has_permission("Inter Branch Sale", "read", throw=True)
	from yht_custom.yht_custom.doctype.inter_branch_sale_settings.inter_branch_sale_settings import allowed_customers

	return allowed_customers()


@frappe.whitelist()
def get_defaults() -> dict:
	"""What a new document starts with, from the settings, so the form is filled when it opens and not only on save."""
	frappe.has_permission("Inter Branch Sale", "read", throw=True)
	settings = frappe.get_cached_doc(SETTINGS)
	return {
		"company": settings.company,
		"cost_center": settings.cost_center,
		"from_warehouse": settings.get("from_warehouse"),
		"price_list": settings.get("price_list"),
	}
