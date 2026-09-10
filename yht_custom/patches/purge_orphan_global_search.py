# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Start the orphan `__global_search` purge, inside a bounded slice of a migrate.

🔴 OPT-IN, AND IT DOES NOTHING UNLESS THE SITE ASKS. `bench migrate` IS the deploy
step, so a patch that deletes on sight spends its budget permanently removing rows
from the client's search index BEFORE anybody has run the pre-flight `report()`
that gate Q11 requires the deploy record to carry. Measured on `yht-test`: 219,430
rows in 122 s, during the migrate, unattended. Q11 says the production purge is
"scheduled separately, after client sign-off, with the pre-flight `report()` output
recorded first"; the two could not both be true, so the patch now defers.

To let it run, put the flag in the site's `site_config.json` first:

    bench --site … set-config yht_purge_global_search 1

Registered in `[post_model_sync]` all the same, so the patch is MARKED AS RUN on
every site and a later migrate does not re-offer it. That is deliberate: this is a
one-off data clean-up, not a schema change, and the manual route below is the
supported one on any site where the flag was never set.

🔴 THIS PATCH DOES NOT FINISH THE JOB EVEN WHEN ENABLED, ON PURPOSE. There are
roughly 890k rows to walk and the database is shared with four LIVE client sites on
the other bench; a migrate that ran the whole purge would hold box I/O for as long
as it took, which is exactly what pushed three of those sites to 5-10 second
responses once already. So it takes a `time_budget` and stops cleanly, and it does
NOT fail the migrate when work remains.

A patch runs once, so the remainder is finished by hand:

    bench --site … execute yht_custom.global_search_purge.report
    bench --site … execute yht_custom.global_search_purge.purge

repeated until it reports `finished: True`. On the CLIENT site that belongs in the
02:00-05:00 window with the authorisation recorded, and the pre-flight `report()`
output goes into the deploy record first. On `yht-test` it may simply be run to
completion.
"""

import frappe
from frappe.utils import cint

from yht_custom.global_search_purge import purge

#: Set in `site_config.json`. Absent or falsy means this patch deletes nothing.
SITE_CONFIG_FLAG = "yht_purge_global_search"


def execute():
	if not cint(frappe.conf.get(SITE_CONFIG_FLAG)):
		print(
			f"  __global_search purge SKIPPED — `{SITE_CONFIG_FLAG}` is not set in site_config.json."
		)
		print("  Pre-flight first: bench --site <site> execute yht_custom.global_search_purge.report")
		print(f"  Then enable it:   bench --site <site> set-config {SITE_CONFIG_FLAG} 1")
		return

	result = purge(time_budget=120)

	if not result.get("finished"):
		print(
			"  __global_search purge is UNFINISHED — deleted "
			f"{result.get('deleted')}, roughly {result.get('remaining_estimate')} rows left to walk."
		)
		print("  Finish it with: bench --site <site> execute yht_custom.global_search_purge.purge")

	skipped = result.get("skipped_missing_table") or {}
	if skipped:
		# Gate Q2: rows naming a DocType with no table are every-one-an-orphan and
		# the least reversible delete there is, so they need a decision rather than
		# a default. Report the count; do not act on it here.
		print("  Rows naming a DocType with no table on this site (NOT purged):")
		for doctype, count in sorted(skipped.items()):
			print(f"    {doctype}: {count}")

	frappe.db.commit()
