# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Unblock item 35's fiscal-year default by removing EMPTY saved filter arrays.

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

ONLY a `filters` key whose value is an empty list, and only under the eight
doctypes item 35 covers. A saved filter someone actually chose is left exactly as
it is — there are real ones on this site (a Delivery Note list pinned to
`owner = <a named user>`, invoice lists pinned to `name like %…%`), and an empty
array is indistinguishable in effect from no key at all, so removing it takes
nothing away from anybody.

`filters` lives NESTED under the view key, not at the top level:

    {"updated_on": "...", "last_view": "List",
     "List": {"filters": [], "sort_by": "modified", "sort_order": "asc"}}

so every view dict is walked, not just the document root.

⚠️ THE CACHE HAS TO GO TOO. `frappe/model/utils/user_settings.py` keeps these in
redis under the `_user_settings` hash keyed `<doctype>::<user>`, and
`sync_user_settings()` writes that cache BACK to the table when a browser asks it
to. Rewriting only the rows would be undone by the first user to load a list.

## Re-runnable

It is idempotent by construction — it only ever removes a key that is an empty
list, so a second run finds nothing to do. It is safe to leave in `patches.txt`.
"""

import json

import frappe

from yht_custom.fiscal_year import DATE_FIELD

#: The same eight doctypes `list_defaults.js` and `fiscal_year.DATE_FIELD` cover.
#: Read from DATE_FIELD rather than repeated, so the three cannot drift.
DOCTYPES = tuple(DATE_FIELD)


def _strip_empty_filters(data: dict) -> bool:
	"""Remove every empty `filters` list in-place. True when something changed."""
	changed = False

	if isinstance(data.get("filters"), list) and not data["filters"]:
		del data["filters"]
		changed = True

	for value in data.values():
		# Each view ("List", "Report", "Kanban", …) carries its own settings dict.
		if isinstance(value, dict) and isinstance(value.get("filters"), list) and not value["filters"]:
			del value["filters"]
			changed = True

	return changed


def execute():
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
		if not isinstance(data, dict) or not _strip_empty_filters(data):
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

	print(f"  cleared an empty saved filter list on {cleared} of {len(rows)} saved list settings")
