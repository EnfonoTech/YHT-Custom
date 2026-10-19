# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Per-site feature switches, because this bench has no per-site code.

🔴 THE PROBLEM THIS EXISTS FOR. `yht-khobhar.enfonoerp.com` (live) and `yht-test`
(UAT) are two sites on ONE bench, so they share ONE `apps/yht_custom`. A template
is read from disk on every render and a `doc_events` handler is registered from
the same `hooks.py` for both — so "deploy to UAT first" is not something the
filesystem can express. Anything new that CHANGES BEHAVIOUR is live on the
client's production site the moment it is pulled.

Most of what this app ships is already naturally gated, and that is not an
accident: a Property Setter, a Custom Field, a Print Format and a Letter Head are
all site-level RECORDS, created by a patch that runs per site. Production does
not see them until `bench --site <live> migrate` runs. The three things that are
NOT gated that way are:

* Python that runs on an event both sites fire
* JavaScript served out of `/assets`
* a change to a template an EXISTING print format already renders

Those read this module instead.

## Using it

`site_config.json`, on the site that should have the feature:

    "yht_features": ["cr_001_spl_address", "cr_012_expense_backfill"]

or, for UAT, the whole set:

    "yht_features": ["all"]

`frappe.conf` is the merged `common_site_config.json` + `site_config.json`, so a
key set on the site wins and a key set on neither reads as "off". **Do not put
`yht_features` in `common_site_config.json`** — that is the one file both sites
share, and it would defeat the entire point of this module.

## Promoting a feature

A feature graduates by having its name added to the LIVE site's
`site_config.json` — not by editing this file. When every site has had a feature
on for long enough that the switch is noise, delete the `enabled()` call and the
constant together; leaving a dead switch is worse than never having had one,
because the next reader cannot tell which side is live.
"""

import frappe

#: Every switch this app knows about. A name not in here is a typo, and
#: `enabled()` says so out loud rather than silently reading False forever —
#: which is the failure mode that makes feature flags worse than no flags.
KNOWN = {
	"cr_001_spl_address": "Address form: SPL lookup button and national-address parser (CR-001)",
	"cr_002_district_fallback": "Print and backfill the district from the legacy `county` column (CR-002)",
	"cr_004_print_heading": "Print-time heading / letterhead / language options (CR-004, CR-005)",
	"cr_006_branch_warehouse": "Branch Configuration fixes the warehouse as well as the cost center (CR-006)",
	"cr_012_expense_backfill": "Purchase Invoice: expense flag derived from the series (CR-012)",
	"cr_013_list_columns": "Transaction lists open on ID/Date/Customer/Status (CR-013)",
	"cr_018_grid_search_width": "Wider link-search dropdown inside a child-table grid cell (CR-018)",
	"cr_019_no_rate_doubleclick": "Double-clicking a Rate cell no longer opens Price Assist (CR-019)",
	# --- client meeting 2026-10-08 ("New Task" sheet), Batch A ------------------
	# Rows 8, 24 and 27 are Property Setters and need no switch: they arrive with
	# each site's own migrate. These four change code that both sites execute.
	"oct08_r07_item_search": "Item picker: every typed word must match code/name/description; ordered by item code (rows 7 + 14)",
	"oct08_r10_new_customer_button": "Create New Customer button only on an unsaved document (row 10)",
	"oct08_r11_quotation_create": "Create > Sales Invoice / Delivery Note on a submitted Quotation (row 11)",
	"oct08_r12_so_delivery_note": "A Sales Order prints as a Delivery Note when Print As says so (row 12)",
	# Osaid, 2026-10-10: rows 20, 23, 24 and 27 stay off the live site until discussed.
	# 20/24/27 are Property Setters and arrive only with a migrate; 23 is code on a
	# shared event, so it gets a switch of its own.
	"oct08_r23_invoice_first_dn_link": "A Delivery Note raised from a Sales Invoice carries the invoice number (row 23)",
	# Rows 24 and 27 are Property Setters written by `after_migrate`; the switch is
	# what lets a live migrate for rows 7–17 leave them out.
	"oct08_r24_prepayment_block": "Payment Entry: prepayment tax sections collapsible, labelled, under the tick (row 24)",
	"oct08_r27_list_filters": "Purchase Invoice list: Is Expense Invoice in the filter row (row 27)",
	# --- client meeting 2026-10-11 ("New Task" sheet, rows 17-37), Tuesday batch ----
	# Each one changes code both sites execute (a doc_event, a JS file, a template
	# argument) or writes something `migrate` would otherwise carry to live.
	"oct11_r17_print_with_arabic": "One 'Print With Arabic' tick on Quotation / Sales Order / Sales Invoice / Delivery Note; the extra toolbar buttons go (rows 17 + 34)",
	"oct11_r20_quotation_id_first": "Quotation list opens with the ID as its first column (row 20)",
	"oct11_r27_type_filter": "One 'Type' dropdown on the Sales Invoice / Delivery Note / Purchase Invoice / Purchase Receipt lists (row 27)",
	"oct11_r28_zatca_additional_number": "ZATCA buyer additional number from the customer address instead of the placeholder text (row 28)",
	"oct11_r29_branch_purchase_order": "Branch users create and edit Purchase Orders, scoped to their branch; PO tile on the dashboard (row 29)",
	"oct11_r36_branch_print_format": "Branch Configuration carries a default print format per document type (row 36)",
	"oct11_r37_print_heading_front": "Print Heading on the front page of the four selling documents, filled in as the document is made (row 37)",
	# --- client meeting 2026-10-11, Wednesday batch (rows 13, 26, 30, 32, 33) ----
	# Row 35 is a guard (tests + one restriction) and has no switch.
	"oct11_r22_other_remarks_front": "Other Remarks moves to the front page of Sales Invoice / Purchase Invoice / Purchase Receipt (row 22)",
	"oct11_r13_sales_history": "Show Sales History popup (sales, purchases, stock, comparison) and the Valuation Rate grid column (row 13)",
	"oct11_r26_session_fiscal_year": "Session-defaults fiscal year drives the list default filters; one-time year pop-up after login (row 26)",
	"oct11_r30_front_details": "Address, contact, PO and sales team on the front page of the selling documents and the KATC prints (row 30)",
	"oct11_r32_doc_number_search": "Global search: a document-number-shaped text returns that series/number first (row 32)",
	"oct11_r33_record_expense": "Record Expense / Expense Invoices entry points, expense print heading and printer-icon format (row 33)",
	# --- client meeting 2026-10-15 (implementation meeting; rows 40, 42, 43, 45, 46, 48) ----
	"oct15_r40_pe_account_lock": "Payment Entry: the account is read-only once a Mode of Payment fills it; no Bank Account lookup for users who cannot read it (row 40)",
	"oct15_r42_quotation_sales_team": "Quotation gets a Sales Team table that fills from the customer (row 42)",
	"oct15_r43_opportunity_bulk_items": "Opportunity items: Download / Upload buttons like Quotation (row 43)",
	"oct15_r45_add_multiple_sort": "'Add Multiple' item pop-up uses the same item search and order as the item picker (row 45)",
	"oct15_r46_connected_numbers": "Connected documents' numbers on the front page of Sales Invoice and Sales Order (row 46)",
	"oct15_r26_new_document_year": "A NEW document must be dated inside the fiscal year chosen for the session; the date picker is limited to it (row 26, 'new also')",
	"oct15_std_remarks_editable": "Standard Remarks editable after submit on Sales / Purchase Invoice, Purchase Receipt, Payment Entry, Stock Entry and Journal Entry; the ledger wording follows (Q&A 5)",
	"oct15_r48_print_pdf_default": "The toolbar Print PDF button opens the document's default / branch print format (row 48)",
	# --- 2026-10-19: HELD, not agreed with the client; lives on feature/inter-branch-sale ---
	"oct19_inter_branch_sale": "Inter Branch Sale: stock to another group entity at a selling price, Stock Entry + Journal Entry, nothing to ZATCA",
}

#: Reads as "every known switch is on". Meant for `yht-test`.
ALL = "all"


def _configured() -> set:
	value = frappe.conf.get("yht_features") or []
	if isinstance(value, str):
		value = [value]
	return {str(v).strip() for v in value if str(v).strip()}


def enabled(name: str) -> bool:
	"""Is this feature switched on for the CURRENT site?

	Raises on an unknown name. A feature switch that silently answers False for a
	misspelled key is indistinguishable from one that is off on purpose, and the
	only symptom is a deploy that appears to do nothing.
	"""
	if name not in KNOWN:
		raise KeyError(f"unknown yht feature {name!r}; add it to yht_custom.features.KNOWN")

	configured = _configured()
	return ALL in configured or name in configured


def active() -> list:
	"""The switches that are on here, for the boot payload and for diagnostics."""
	return sorted(name for name in KNOWN if enabled(name))


def report() -> dict:
	"""``bench --site … execute yht_custom.features.report``."""
	summary = {"site": frappe.local.site, "configured": sorted(_configured()), "active": active()}
	print(frappe.as_json(summary, indent=1))
	return summary
