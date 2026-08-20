# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Recompute `custom_total_line_item_discount` on every existing document.

WHY THIS IS NEEDED AT ALL, given the field was created only today.

The COLUMN already existed. The legacy team had a field of the same name; Step 1
deleted the Custom Field record but **deleting a Custom Field does not drop its
column, and it does not touch the data in it**. So the moment this app declared
the field again, thousands of documents came back carrying the legacy system's
numbers under our label — measured on Sales Invoice `KSIN-25-0983`: stored 170.00
against a true consolidated discount of 167.38, because the legacy figure summed
only the positive `discount_amount` values and ignored a row priced 2.62 ABOVE
the list rate.

Nothing user-facing was wrong — the print formats compute from the rows and never
read this field — but a stored number that disagrees with the report it is named
after is a trap for whoever filters on it next.

One UPDATE per doctype, no parameters interpolated, driven entirely by the item
rows. Idempotent: running it twice produces the same values.
"""

import frappe

from yht_custom.discount_totals import DISCOUNT_DOCTYPES, TOTAL_FIELD


def execute():
	for doctype in DISCOUNT_DOCTYPES:
		if not frappe.db.has_column(doctype, TOTAL_FIELD):
			continue

		parent = f"tab{doctype}"
		child = f"tab{doctype} Item"

		# Mirrors discount_totals.line_discount exactly: the rate delta where there
		# is a price-list rate to measure against, the per-unit discount otherwise.
		frappe.db.sql(
			f"""
			UPDATE `{parent}` p
			SET p.`{TOTAL_FIELD}` = COALESCE((
				SELECT SUM(
					CASE WHEN i.price_list_rate > 0
						THEN (i.price_list_rate - i.rate) * i.qty
						ELSE i.discount_amount * i.qty
					END
				)
				FROM `{child}` i WHERE i.parent = p.name
			), 0)
			"""
		)
		frappe.db.commit()
