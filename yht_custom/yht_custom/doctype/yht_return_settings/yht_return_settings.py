# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Switches for the return flow that are a branch policy rather than a rule.

Only one so far, and it exists because the client's standing decision and the
operator's habit disagree: `return_flow.enforce_return_stock_route` insists that a
return of delivered goods is raised on the Delivery Note, and some branches want to
raise the credit note first and bring the stock back afterwards. That is a choice,
not a correctness question, so it lives here rather than in the code.
"""

import frappe
from frappe.model.document import Document


class YHTReturnSettings(Document):
	pass


def allow_delivery_note_from_sales_return() -> bool:
	"""The switch, read the cheap way.

	`get_single_value` reads one column and is cached; `get_doc` on a Single loads
	every field. This is called from `before_validate` on two doctypes, so it runs on
	every invoice save on the site.
	"""
	if not frappe.db.exists("DocType", "YHT Return Settings"):
		# The app can be ahead of the migrate that creates the doctype.
		return False
	return bool(
		frappe.db.get_single_value("YHT Return Settings", "allow_delivery_note_from_sales_return")
	)
