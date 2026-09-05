# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Backfill `custom_fiscal_year` on documents that predate the field.

🔴 THIS PATCH CREATES THE FIELDS ITSELF, ON PURPOSE. Patches run BEFORE
`after_migrate`, so a backfill that assumed `ensure_fiscal_year_custom_fields`
had already run would update a column that does not exist yet — or, worse, find
nothing to do, succeed, and mark itself done forever. Provisioning first is what
makes this correct on a fresh migrate and idempotent on a re-run.
"""

import frappe

from yht_custom.fiscal_year import DATE_FIELD, FIELDNAME, backfill


def execute():
	from yht_custom.setup import ensure_fiscal_year_custom_fields

	ensure_fiscal_year_custom_fields()
	frappe.db.commit()

	written = backfill()

	for doctype, count in sorted(written.items()):
		remaining = frappe.db.count(doctype, {FIELDNAME: ["in", ("", None)]})
		print(f"  {doctype}: filled {count}, still empty {remaining}")
