# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""`custom_fiscal_year` — the fiscal year, derived from the document's own date.

WHY A STORED FIELD AT ALL, WHEN ERPNEXT ALREADY FILTERS BY FISCAL YEAR.
`erpnext/startup/filters.py` registers a "Fiscal Year" filter operator through the
`filters_config` hook, so any list view can already filter a Date field by year
with nothing stored. That covers filtering and only filtering: it does not put the
year ON the document where staff read it, and it cannot be grouped, sorted,
exported or reported on. This field is for that, and it makes the list filter a
one-click dropdown instead of a two-step operator change.

🔴 NEVER GIVE THIS FIELD A FIXED DEFAULT. The client's previous system did
exactly that — a Link field defaulting to `2026` — and the migrated data still
carries the damage: 731 Sales Invoices are stamped FY 2026 while dated as early as
2024-08-01. A fiscal year that does not follow the posting date is worse than none
at all, because it looks authoritative. The value is ALWAYS computed here.
"""

import frappe
from frappe.utils import getdate

#: Written down once so the hook, the field definition, the patch and the tests
#: cannot drift apart.
FIELDNAME = "custom_fiscal_year"

#: Which date each doctype is filed under. Selling documents date on
#: `transaction_date`; accounting and stock documents post on `posting_date`.
#: Reading the wrong one files a document under the wrong year silently, so the
#: mapping is explicit rather than a `posting_date or transaction_date` guess.
#: `hooks.py` registers exactly these doctypes — a test asserts the two agree.
DATE_FIELD = {
	"Sales Invoice": "posting_date",
	"Purchase Invoice": "posting_date",
	"Delivery Note": "posting_date",
	"Purchase Receipt": "posting_date",
	"Payment Entry": "posting_date",
	"Journal Entry": "posting_date",
	"Sales Order": "transaction_date",
	"Quotation": "transaction_date",
}


def resolve(date, company=None, include_disabled=False) -> str:
	"""The Fiscal Year covering `date`, or `""` when none does.

	ERPNext's own resolver answers first, called with `boolean=True` because that
	form returns `False` instead of raising `FiscalYearError`. That matters: a
	document must never become unsaveable because nobody has created next year's
	Fiscal Year yet. A missing year leaves the field empty and the document saves.

	`include_disabled` is for the BACKFILL ONLY. `get_fiscal_years` filters on
	`disabled = 0`, so a historical document dated inside a closed year resolves to
	nothing — on this site FY 2022 and 2023 are disabled and ten Sales Invoices sit
	in 2023. New documents deliberately do NOT get that fallback: filing a fresh
	document into a closed year should stay impossible.
	"""
	if not date:
		return ""

	from erpnext.accounts.utils import get_fiscal_year

	try:
		found = get_fiscal_year(getdate(date), company=company, boolean=True)
	except Exception:
		# Never let a fiscal-year lookup be the reason a document cannot be saved.
		found = False

	if found:
		# `(name, year_start_date, year_end_date)`.
		return found[0][0]

	if not include_disabled:
		return ""

	row = frappe.db.sql(
		"""select name from `tabFiscal Year`
			   where %s between year_start_date and year_end_date
			   order by disabled asc, year_start_date desc
			   limit 1""",
		(getdate(date),),
	)
	return row[0][0] if row else ""


def set_fiscal_year(doc, method=None) -> None:
	"""`validate` hook — stamp the fiscal year from the document's own date.

	Always recomputes. The field is read-only in the UI, so the stored value has no
	source of truth other than the date, and recomputing is what keeps the two in
	step when somebody backdates a draft.

	The `meta.get_field` guard keeps this inert on a bench where the code has been
	deployed but `after_migrate` has not yet created the Custom Field — otherwise
	every save on eight doctypes would fail for the window between the two.
	"""
	date_field = DATE_FIELD.get(doc.doctype)
	if not date_field:
		return
	if not doc.meta.get_field(FIELDNAME):
		return

	doc.set(FIELDNAME, resolve(doc.get(date_field), company=doc.get("company")))


def backfill(doctypes=None) -> dict:
	"""Derive the field on every existing document. Returns rows written per doctype.

	🔴 THIS OVERWRITES, AND IT HAS TO. `custom_fiscal_year` did NOT start empty
	on this site: the column arrived with the migration, already populated on ~4,055
	documents by the client's previous system (untouched `yht-test` still shows it —
	585 Purchase Invoices, 380 Journal Entries, and so on). A fill-only-empty backfill
	silently inherits all of that, and four of those rows disagree with their own
	posting date — e.g. `KSPI-25-0104-1` dated 2025-01-01 carrying FY 2024. The field
	is defined as derived from the date, so an inherited value has no standing.

	A joined UPDATE, not `doc.save()`: these are submitted accounting documents, and
	re-saving 17,000 of them to populate one print-hidden field would re-run every
	validation and rewrite `modified` for nothing.

	TWO PASSES, and the order is the point. Pass one matches ACTIVE fiscal years and
	overwrites, so a document is never pulled into a closed year while an open one
	also covers the date. Pass two fills only what is still empty, allowing disabled
	years — which is how the ten 2023 Sales Invoices get their closed year.

	The doctype and column names are interpolated, which is safe here and only here:
	both come from `DATE_FIELD` above — a module constant, never a caller — and the
	assert enforces it. Table and column names cannot be bound as parameters.
	"""
	written = {}
	for doctype in doctypes or DATE_FIELD:
		assert doctype in DATE_FIELD, f"{doctype} is not a fiscal-year doctype"
		date_field = DATE_FIELD[doctype]
		table = f"tab{doctype}"
		count = 0

		# Pass 1 — active years, overwriting whatever was inherited.
		frappe.db.sql(
			f"""update `{table}` t
				join `tabFiscal Year` f
				  on t.`{date_field}` between f.year_start_date and f.year_end_date
				 and f.disabled = 0
				 set t.`{FIELDNAME}` = f.name
				 where ifnull(t.`{date_field}`, '') <> ''
				   and ifnull(t.`{FIELDNAME}`, '') <> f.name"""
		)
		count += frappe.db.sql("select row_count()")[0][0] or 0

		# Pass 2 — closed years, for documents no active year covers.
		frappe.db.sql(
			f"""update `{table}` t
				join `tabFiscal Year` f
				  on t.`{date_field}` between f.year_start_date and f.year_end_date
				 set t.`{FIELDNAME}` = f.name
				 where ifnull(t.`{date_field}`, '') <> ''
				   and ifnull(t.`{FIELDNAME}`, '') = ''"""
		)
		count += frappe.db.sql("select row_count()")[0][0] or 0

		frappe.db.commit()
		written[doctype] = count

	return written
