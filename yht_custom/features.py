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
