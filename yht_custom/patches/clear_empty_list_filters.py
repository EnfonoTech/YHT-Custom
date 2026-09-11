# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Unblock item 35's fiscal-year default by repairing saved list filters.

🔴 WHY THIS PATCH EXISTS AT ALL. `list_view.js::setup_defaults` picks the list's
opening filters like this:

    if (Array.isArray(this.view_user_settings.filters))   // Priority 1
        this.filters = this.validate_filters(saved_filters);
    else                                                  // Priority 2
        this.filters = (this.settings.filters || []).map(...)

`frappe.listview_settings[dt].filters` — which is all `public/js/list_defaults.js`
can set — is Priority 2. And **`Array.isArray([])` is `true`**, so a user who has
opened the list once and has an EMPTY saved array takes Priority 1 with nothing in
it, and the default never applies again. Measured on `yht-khobhar` 2026-09-10: 591
saved list settings across these eight doctypes, 92 distinct users. Without this
patch item 35 is a feature that does nothing for everyone who has used the system.

🔴 AND WHY IT IS NOT JUST DONE IN JS. `frappe.listview_settings[dt].onload` was
tried first and does not work: `onload` fires from `setup_view()`
(`list_view.js:333`), which runs after `setup_defaults` has already built the
filter area and started the fetch. Assigning `listview.filters` there changes
nothing on screen. `filter_area.add()` would work but costs a second query on
every list open and overrides a user who deliberately cleared their filters.

## What it touches, and what it deliberately does not

Two things block the default, and it fixes both, under the eight item-35
doctypes only:

1. **An EMPTY `filters` array.** Indistinguishable in effect from no key at all,
   so removing it takes nothing away from anybody.
2. **A `company =` clause naming a company this site does not have** — legacy
   settings imported from the other group entities. Those are REPOINTED to the
   user's Session Defaults -> Default Company, read per user via
   `frappe.defaults.get_user_default`, never hardcoded. The filter keeps doing
   what the operator meant; it just names a company that exists.

A filter someone actually chose against a real value is left exactly as it is —
there are real ones here (a Delivery Note list pinned to `owner = <a named
user>`, invoice lists pinned to `name like %...%`).

`filters` lives NESTED under the view key, not at the top level:

    {"updated_on": "...", "last_view": "List",
     "List": {"filters": [], "sort_by": "modified", "sort_order": "asc"}}

so every view dict is walked, not just the document root.

⚠️ THE CACHE HAS TO GO TOO. `frappe/model/utils/user_settings.py` keeps these in
redis under the `_user_settings` hash keyed `<doctype>::<user>`, and
`sync_user_settings()` writes that cache BACK to the table when a browser asks it
to. Rewriting only the rows would be undone by the first user to load a list.

## Re-runnable

Idempotent by construction: a second run finds no empty arrays left and no
company clause naming a missing company, so it changes nothing. Safe to leave in
`patches.txt`.
"""

import json

import frappe

from yht_custom.fiscal_year import DATE_FIELD

#: The same eight doctypes `list_defaults.js` and `fiscal_year.DATE_FIELD` cover.
#: Read from DATE_FIELD rather than repeated, so the three cannot drift.
DOCTYPES = tuple(DATE_FIELD)


def _live_companies() -> set:
	return set(frappe.get_all("Company", pluck="name"))


def _repoint_dead_company(filters: list, user: str, companies: set) -> bool:
	"""Rewrite a `company =` clause naming a company this site does not have.

	🔴 THE SECOND WAY ITEM 35 DIES, AND IT IS ITEM 27 WEARING A DIFFERENT HAT.
	The legacy import left saved list filters pointing at the OTHER group
	entities — measured on this site, Administrator's Sales Invoice list is
	pinned to `KATHOOM JEDDAH TRADING CO.` and Sales Order to
	`ALBINA AL AMTHAL TRADING CO.`, neither of which is a Company here.
	`setup_defaults` takes Priority 1 because a filters array exists,
	`validate_filters` then silently drops the impossible clause, and the list
	ends up with NO filter and no fiscal-year default either.

	Repointed, not deleted. The clause is rewritten to that user's **Session
	Defaults → Default Company**, read per user at patch time via
	`frappe.defaults.get_user_default` — so the value follows whatever each
	operator actually has set, and nothing is hardcoded. A user with no default
	set loses only the clause, which could never have matched anything anyway.
	"""
	changed = False
	default_company = frappe.defaults.get_user_default("company", user)

	for clause in list(filters):
		if not isinstance(clause, list) or len(clause) < 4:
			continue
		if clause[1] != "company" or clause[2] not in ("=", "in"):
			continue
		if clause[3] in companies:
			continue

		if default_company:
			clause[3] = default_company
		else:
			filters.remove(clause)
		changed = True

	return changed


def _strip_empty_filters(data: dict, user: str, companies: set) -> bool:
	"""Fix every view's filters in-place. True when something changed."""
	changed = False

	def _fix(holder):
		nonlocal changed
		value = holder.get("filters")
		if not isinstance(value, list):
			return
		if value and _repoint_dead_company(value, user, companies):
			changed = True
		# Re-read: repointing can empty the list, and an empty array is exactly
		# what blocks Priority 2.
		if not holder["filters"]:
			del holder["filters"]
			changed = True

	_fix(data)
	for value in data.values():
		# Each view ("List", "Report", "Kanban", …) carries its own settings dict.
		if isinstance(value, dict):
			_fix(value)

	return changed


def execute():
	companies = _live_companies()

	rows = frappe.db.sql(
		"""select `user`, `doctype`, `data` from `__UserSettings`
		   where `doctype` in %(doctypes)s""",
		{"doctypes": DOCTYPES},
		as_dict=True,
	)

	cleared = 0
	for row in rows:
		try:
			data = json.loads(row.data or "{}")
		except (TypeError, ValueError):
			# A corrupt row is somebody's UI preference, not our data to repair.
			continue
		if not isinstance(data, dict) or not _strip_empty_filters(data, row.user, companies):
			continue

		frappe.db.sql(
			"""update `__UserSettings` set `data` = %s
			   where `user` = %s and `doctype` = %s""",
			(json.dumps(data), row.user, row.doctype),
		)
		cleared += 1

	# See the docstring — without this the cached copy is written straight back.
	frappe.cache.delete_key("_user_settings")
	frappe.db.commit()

	print(f"  repaired the saved list filters on {cleared} of {len(rows)} saved list settings")
