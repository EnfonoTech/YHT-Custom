# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""The data half of the 2026-09-23 change requests, in one re-runnable pass.

Four backfills, each idempotent and each delegating to the module that owns the
rule so the patch cannot drift from the live behaviour:

* **CR-002** `address_district.backfill` (switched) — the legacy `county` value copied into
  `custom_area`, which is the field `ksa_compliance` reads for `buyer_district`,
  but ONLY where it classifies as a genuine district. A `county` holding the city
  again, a street or the literal string "NULL" is left for the client.
* **CR-008** `dn_links.backfill` — the Sales Order and Sales Invoice numbers onto
  every existing Delivery Note's front page.
* **CR-004/005** `print_heading.backfill_headings` — the derived print heading
  onto documents that carry none, so the bulk edit the client asked for starts
  from values rather than from blanks.
* **CR-012** `expense_invoice.backfill_expense_flag` — the expense flag onto the
  384 Purchase Invoices whose series already says they are expenses.

🔴 THREE OF THE FOUR ARE BEHIND FEATURE SWITCHES, AND THAT IS THE POINT. This
bench serves the client's LIVE site and UAT off one `apps/yht_custom`, so a
migrate on production would otherwise run every one of these the moment the code
lands. The heading and expense backfills change how thousands of existing
documents present and validate, so they wait for `cr_004_print_heading` /
`cr_012_expense_backfill` in that site's own `site_config.json`, and the district
backfill waits for `cr_002_district_fallback` because the value it writes reaches
a tax invoice. Only the delivery-note backfill runs unswitched: its two fields do
not exist until the migrate that creates them, and nothing else reads them.

Re-running is safe and cheap: every backfill compares before it writes.
"""

import frappe

from yht_custom import address_district, dn_links, expense_invoice, features, print_heading


def execute():
	results = {}

	# 🔴 THE FIELDS THESE BACKFILLS WRITE ARE CREATED IN `after_migrate`, WHICH RUNS
	# AFTER PATCHES. On the first migrate the Delivery Note columns and the four
	# new `Print Heading` records did not exist yet, so the backfill quietly wrote
	# nothing and reported success — measured on yht-test, Quotation, Sales Order
	# and Purchase Order all came back 0. Both provisioning steps are idempotent,
	# so calling them here costs nothing on every subsequent run and removes the
	# ordering dependency entirely.
	print_heading.setup_print_headings()
	dn_links.setup_delivery_note_links()
	frappe.db.commit()

	if features.enabled("cr_002_district_fallback") and frappe.db.has_column("Address", "custom_area"):
		# Recheck FIRST: a value this module derived under an older rule has to be
		# released before the current rule can decline to write it again.
		results["cr_002_recheck"] = address_district.recheck(commit=True)
		results["cr_002_district"] = address_district.backfill(commit=True)
	else:
		results["cr_002_district"] = "skipped — cr_002_district_fallback is off here"

	results["cr_008_delivery_note_links"] = dn_links.backfill(commit=True)

	# CR-013 — the first version of `list_columns` chose list columns with
	# `in_list_view` Property Setters. Those are rows, not code, so they keep
	# working after the code changed; delete them or the list is driven by two
	# mechanisms at once. Safe to re-run: deleting what is already gone is a no-op.
	from yht_custom import list_columns

	results["cr_013_stale_setters"] = list_columns.drop_stale_in_list_view_setters()
	frappe.db.commit()

	if features.enabled("cr_004_print_heading"):
		results["cr_004_print_headings"] = print_heading.backfill_headings(commit=True)
	else:
		results["cr_004_print_headings"] = "skipped — cr_004_print_heading is off here"

	if features.enabled("cr_012_expense_backfill"):
		results["cr_012_expense_flag"] = expense_invoice.backfill_expense_flag(commit=True)
	else:
		results["cr_012_expense_flag"] = "skipped — cr_012_expense_backfill is off here"

	print(frappe.as_json(results, indent=1))
