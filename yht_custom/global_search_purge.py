# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Purge orphan `__global_search` rows, chunked and re-runnable.

Client sheet item 27. Roughly 890k rows in this site's search index name
documents that were never imported — they came across with six sister entities'
data and every one of them is noise in the awesome bar.

THREE FACTS SHAPE EVERY DECISION HERE.

1. **The table is MyISAM.** `frappe/database/mariadb/database.py:308` creates it
   with `ENGINE=MyISAM`, a `FULLTEXT(content)` index and a unique key on
   `(doctype, name)`. There is no transaction: `frappe.db.rollback()` cannot
   undo a single delete. Every delete here is immediate and final, which is why
   nothing is deleted that has not just been proved to have no record.
2. **MyISAM takes a table-level write lock**, but the table lives in *this
   site's* database, so it does not lock the four live client sites on the other
   bench. The shared exposure is box I/O — which is exactly what degraded them
   once before. Small batches, and a pause between them.
3. **It is pure derived index data.** The worst case of an over-delete is a
   document missing from the awesome bar until it is next saved, repairable one
   doctype at a time with `frappe.utils.global_search.rebuild_for_doctype`. That
   is the whole safety argument, and it is why a targeted purge is acceptable
   where a full rebuild is not.

**NEVER** bench's whole-index rebuild command, never the every-doctype rebuild
helper in `frappe.utils.global_search`, and never an in-place table
reorganisation — any of those is a full MyISAM rebuild of 890k rows with the
table locked throughout, on a box shared with four live sites. A test greps this
file for the name of each one.

⚠️ NO SQL JOIN ANYWHERE IN THIS MODULE, DELIBERATELY. `__global_search` is
created `COLLATE=utf8mb4_general_ci` while this site's doctype tables are
`utf8mb4_unicode_ci`, and joining the two raises *Illegal mix of collations*
(measured on yht-khobhar, 2026-09-10). Rather than paper over that with an
explicit `COLLATE` — which has to guess the site's charset and silently drops
the index — existence is asked as `WHERE name IN (…)` against the doctype's own
table, where the values are bound literals and take the column's own collation.
It is also one rule for what counts as an orphan, shared by `report` and
`purge`.
"""

import time

import frappe
from frappe.utils import cint, flt

TABLE = "__global_search"

#: Small enough that one page's table lock is under a human-perceptible
#: threshold on a box that is also serving four live sites.
DEFAULT_BATCH = 2000
DEFAULT_SLEEP = 0.2


def _doctype_counts(only=None):
	"""``[(doctype, rows)]`` straight off the table, biggest group first.

	Parameterless raw SQL: `__global_search` has no DocType record, so nothing
	that wants metadata can be pointed at it — the same situation as `tabSeries`.
	"""
	rows = frappe.db.sql(
		"""select doctype, count(*) from `__global_search`
		   group by doctype order by 2 desc"""
	)
	counts = [(row[0], cint(row[1])) for row in rows if row[0]]
	if only:
		wanted = set(only)
		counts = [row for row in counts if row[0] in wanted]
	return counts


def _pages(doctype, batch_size):
	"""Successive pages of `name`, paged on the key rather than by position.

	🔴 KEYSET, AND IT HAS TO BE. Paging by position skips rows the moment you
	start deleting behind yourself — half the orphans would survive a run and the
	job would never converge. `name > %s ORDER BY name` rides the shipped
	`(doctype, name)` unique index and is correct however many rows the previous
	page removed.
	"""
	cursor = ""
	while True:
		rows = frappe.db.sql(
			"""select name from `__global_search`
			   where doctype = %s and name > %s
			   order by name
			   limit %s""",
			(doctype, cursor, cint(batch_size)),
		)
		if not rows:
			return
		yield [row[0] for row in rows]
		cursor = rows[-1][0]


def _orphans(doctype, names):
	"""Which of these names have no record. One query, no join.

	See the module docstring for why the join is the thing being avoided. The
	doctype reaches the query builder as a table name and it came out of
	`__global_search`, i.e. out of DATA — so every caller has already put it
	through `frappe.db.table_exists`, which is a membership test against the
	real table list. That whitelist is what makes naming the table here safe.
	"""
	if not names:
		return []
	table = frappe.qb.DocType(doctype)
	present = set(
		frappe.qb.from_(table).select(table.name).where(table.name.isin(list(names))).run(pluck=True)
	)
	return [name for name in names if name not in present]


def report(batch_size=DEFAULT_BATCH, sleep=DEFAULT_SLEEP, time_budget=None, doctypes=None) -> dict:
	"""Read-only pre-flight. THIS IS WHAT GOES INTO THE DEPLOY RECORD.

	    bench --site … execute yht_custom.global_search_purge.report

	Per doctype: how many rows the index holds, how many of them name a document
	that does not exist, and whether the doctype has a table on this site at all.
	Writes nothing.

	🔴 THROTTLED LIKE `purge`, AND FOR THE SAME REASON — writing nothing is not
	the same as costing nothing. This walks ~890k rows two queries to the page,
	and on `yht-khobhar` that MariaDB is shared with four live client sites on the
	other bench; a 10 GB restore run outside the window once took three of them
	from sub-second to 5-10 s with hard timeouts. The runbook makes this step 1,
	so **the pre-flight belongs inside 02:00-05:00 IST too**, not just the purge
	it precedes.

	`time_budget` stops the walk cleanly and reports `finished: False` per
	doctype, so a bounded look is possible without committing to the whole index.
	"""
	started = time.monotonic()
	budget = flt(time_budget) if time_budget is not None else None

	def _out_of_time():
		return budget is not None and (time.monotonic() - started) >= budget

	result = {}

	for doctype, total in _doctype_counts(doctypes):
		table_exists = bool(frappe.db.table_exists(doctype))
		finished = True
		if not table_exists:
			# No table means every row is an orphan by definition — and that is the
			# largest and least reversible group, which is why `purge` will not
			# touch it without being asked. See gate decision Q2.
			orphans = total
		else:
			orphans = 0
			for names in _pages(doctype, batch_size):
				orphans += len(_orphans(doctype, names))
				if _out_of_time():
					finished = False
					break
				time.sleep(sleep)

		result[doctype] = {
			"total": total,
			"orphans": orphans,
			"table_exists": table_exists,
			"finished": finished,
		}
		print(
			f"  {doctype}: {total} rows, {orphans} orphaned, "
			f"table_exists={table_exists}, finished={finished}"
		)

		if _out_of_time():
			break

	return result


def purge(
	batch_size=DEFAULT_BATCH,
	sleep=DEFAULT_SLEEP,
	time_budget=None,
	doctypes=None,
	include_missing=False,
) -> dict:
	"""Delete rows naming a document that does not exist. Idempotent.

	    bench --site … execute yht_custom.global_search_purge.purge

	Idempotent by construction: it only ever deletes rows it has just proved have
	no record, so a second run finds nothing.

	`time_budget` is in seconds and is what keeps a routine `bench migrate`
	bounded; the run stops cleanly and reports `finished: False` with an estimate
	of what is left. `doctypes` scopes a targeted re-run.

	`include_missing` covers rows naming a DocType with no table on this site.
	Gate decision **Q2**: those are skipped and counted by default. Every one of
	them is an orphan by definition, which makes it both the largest group and
	the least reversible delete — and an app that is merely uninstalled may be
	coming back. That needs a human decision, not a default.
	"""
	started = time.monotonic()
	budget = flt(time_budget) if time_budget is not None else None

	deleted = 0
	remaining = 0
	finished = True
	skipped_missing_table = {}

	def spent():
		return budget is not None and (time.monotonic() - started) >= budget

	for doctype, total in _doctype_counts(doctypes):
		if spent():
			finished = False
			remaining += total
			continue

		table_exists = bool(frappe.db.table_exists(doctype))
		if not table_exists and not include_missing:
			skipped_missing_table[doctype] = total
			continue

		# 🔴 PER DOCTYPE, NOT THE RUN-WIDE `deleted`. `total` is THIS doctype's row
		# count; subtracting a cumulative figure that already carries every earlier
		# doctype's deletions mixes two scopes, under-reports from the second
		# doctype onwards, and can read 0 with work still outstanding. That number
		# is what an operator reads out of a 120-second patch slice to decide
		# whether to run again.
		removed = 0

		for names in _pages(doctype, batch_size):
			# A missing table means the whole page is orphaned; there is nothing to
			# ask and nowhere to ask it.
			doomed = names if not table_exists else _orphans(doctype, names)
			if doomed:
				frappe.db.delete(TABLE, {"doctype": doctype, "name": ("in", doomed)})
				deleted += len(doomed)
				removed += len(doomed)

			# MyISAM gives us no transaction, so this commit is a formality for the
			# table itself — it is here to keep the surrounding session short and to
			# let the pause actually release the box.
			frappe.db.commit()
			time.sleep(sleep)

			if spent():
				finished = False
				# What a re-run still has to WALK: every surviving row of this
				# doctype, because the pager re-examines each one for orphanhood.
				remaining += max(total - removed, 0)
				break

	result = {
		"deleted": deleted,
		"remaining_estimate": remaining,
		"finished": finished,
		"skipped_missing_table": skipped_missing_table,
	}
	print(f"  deleted {deleted}, finished={finished}, remaining_estimate={remaining}")
	if skipped_missing_table:
		print("  skipped (no table on this site — see gate Q2):")
		for doctype, count in sorted(skipped_missing_table.items()):
			print(f"    {doctype}: {count}")
	return result
