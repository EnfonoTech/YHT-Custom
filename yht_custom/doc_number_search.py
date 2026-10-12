# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Row 32 (meeting 2026-10-11) — a document-number-shaped search finds that number first.

The awesomebar's "Search for X" opens the search dialog, which calls
`frappe.utils.global_search.search` through `/api/method/…` → `handler.execute_cmd`.
`execute_cmd` applies `override_whitelisted_methods`, so — unlike the Link picker
(gotcha 118) — a server-side override DOES reach this one and no client lever is needed.

Upstream is a FULLTEXT `MATCH … AGAINST` per word ordered by relevance, so `KSIN-26-0701`
returns `KSIN-25-0701` first (a token match in another year) and `KSIN` returns twenty
invoices from 2024. Here a single document-number-shaped token also does a name PREFIX
lookup on `__global_search.doctype_name` (a BTREE: ~8 ms), newest first, and puts those
hits ahead of whatever upstream returned.

## What is and is not promised

* A document-NAME PREFIX is matched first, newest first (`name DESC`).
* Matching is case-INSENSITIVE and not whole-word (`utf8mb4_general_ci`, and MariaDB
  full-text): `KSIN` also finds `ksin-…`. Case-sensitive or whole-word matching is NOT
  supported, and the UI must not claim it.
* Pagination (`start > 0`) falls straight through to upstream, so a "load more" page can
  repeat a hit that the first page's prefix block already showed.
* Upstream does not row-filter its own results (only doctype read) — unchanged and out of
  scope. The prefix block IS row-filtered through `frappe.get_list`, so a branch user is
  never handed another branch's document number first.

With the switch off this is a plain pass-through to upstream.
"""

import re

import frappe
from frappe.utils import cint
from frappe.utils import global_search

from yht_custom import features

#: One token that looks like a document name. Anything else is upstream's.
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{1,39}$")

#: Rank given to a prefix hit; upstream's MATCH ranks are small floats.
PREFIX_RANK = 1000


def _like_prefix(text: str) -> str:
	"""`text` as a LIKE pattern for a prefix, with the wildcards escaped."""
	escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
	return escaped + "%"


@frappe.whitelist()
def search(text: str, start: int = 0, limit: int = 20, doctype: str = ""):
	"""Same signature as `frappe.utils.global_search.search` (frappe 15 validates annotations)."""
	if not features.enabled("oct11_r32_doc_number_search"):
		return global_search.search(text, start, limit, doctype)
	if cint(start) > 0 or not text or not TOKEN.match(text):
		return global_search.search(text, start, limit, doctype)

	limit = cint(limit) or 20
	hits = _prefix_hits(text, limit, doctype)
	if not hits:
		return global_search.search(text, start, limit, doctype)

	seen = {(row["doctype"], row["name"]) for row in hits}
	rest = [
		row
		for row in (global_search.search(text, start, limit, doctype) or [])
		if (row.get("doctype"), row.get("name")) not in seen
	]
	return (hits + rest)[:limit]


def _prefix_hits(text: str, limit: int, doctype: str) -> list:
	from frappe.desk.doctype.global_search_settings.global_search_settings import (
		get_doctypes_for_global_search,
	)

	# Exactly upstream's rule for which doctypes may be searched at all.
	allowed = set(get_doctypes_for_global_search()) & set(frappe.get_user().get_can_read())
	if doctype:
		allowed &= {doctype}
	if not allowed:
		return []

	# Over-fetch: the row filter below can drop rows, and the cap applies afterwards.
	fetch = min(limit * 5, 200)
	rows = frappe.db.sql(
		"""SELECT doctype, name, content FROM `__global_search`
		WHERE name LIKE %s ESCAPE '\\\\' AND doctype IN %s
		ORDER BY name DESC LIMIT %s""",
		(_like_prefix(text), tuple(sorted(allowed)), fetch),
		as_dict=True,
	)

	by_doctype = {}
	for row in rows:
		by_doctype.setdefault(row.doctype, []).append(row.name)

	visible = {}
	for dt, names in by_doctype.items():
		try:
			# Applies permission_query_conditions and User Permissions.
			visible[dt] = set(frappe.get_list(dt, filters={"name": ["in", names]}, pluck="name"))
		except Exception:
			frappe.clear_messages()
			frappe.log_error(frappe.get_traceback(), f"doc_number_search: get_list failed for {dt}")
			visible[dt] = set()

	hits = []
	for row in rows:
		if row.name in visible.get(row.doctype, ()):
			hits.append(
				{"doctype": row.doctype, "name": row.name, "content": row.content, "rank": PREFIX_RANK}
			)
		if len(hits) >= limit:
			break
	return hits
