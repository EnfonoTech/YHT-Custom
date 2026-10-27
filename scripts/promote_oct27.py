"""Promote the 2026-10-27 rows to a site: switches on, the five form steps, prints proven unchanged.

    cd /home/v15/yht-bench/sites
    sudo -u v15 -H ../env/bin/python /path/to/promote_oct27.py yht-khobhar.enfonoerp.com [--apply]

Without `--apply` it only hashes (a dry run that writes nothing). With it, in ONE process so the documents
and the formats compared are the same before and after:

1. pins the newest submitted document of the four selling doctypes and hashes every enabled print format
   of those doctypes on it (the client's own defaults included, not only KATC — gotcha 107);
2. adds the six `oct27_*` switches to THIS site's `site_config.json` (never common_site_config);
3. runs the five provisioning steps (no migrate: a live migrate would also carry unrelated pending patches);
4. clears the cache and hashes again. The last line is `N <count> DIFF <count>`.

Q6 (`oct27_print_preview`) changes only which URL the toolbar button opens, so it has no step.
"""

import hashlib
import json
import os
import sys

import frappe

SWITCHES = [
	"oct27_other_remarks_hidden",
	"oct27_cash_hides_due_date",
	"oct27_company_tax_id_hidden",
	"oct27_attention_hidden",
	"oct27_no_quick_customer",
	"oct27_print_preview",
]
DOCTYPES = ("Sales Invoice", "Quotation", "Sales Order", "Delivery Note")


def _pairs():
	out = []
	for dt in DOCTYPES:
		name = frappe.db.get_value(dt, {"docstatus": 1}, "name", order_by="creation desc")
		if not name:
			continue
		for fmt in frappe.get_all("Print Format", {"doc_type": dt, "disabled": 0}, pluck="name"):
			out.append((dt, name, fmt))
	return sorted(out)


def _hashes(pairs):
	res = {}
	for dt, name, fmt in pairs:
		try:
			html = frappe.get_print(dt, name, fmt)
			res[(dt, name, fmt)] = hashlib.sha256(html.encode()).hexdigest()[:16]
		except Exception as e:  # an ERROR is never a pass: it is reported, and counted as a diff
			res[(dt, name, fmt)] = "ERROR " + type(e).__name__
		frappe.db.rollback()  # get_print commits (gotcha 84); nothing here should persist
	return res


def _enable_switches(site):
	path = os.path.join(os.getcwd(), site, "site_config.json")
	with open(path) as f:
		conf = json.load(f)
	current = conf.get("yht_features") or []
	added = [s for s in SWITCHES if s not in current]
	conf["yht_features"] = current + added
	with open(path, "w") as f:
		json.dump(conf, f, indent=1, sort_keys=True)
	frappe.local.conf = frappe._dict(frappe.get_site_config())
	return added


def main(site, apply):
	frappe.init(site=site, sites_path=os.getcwd())
	frappe.connect()
	frappe.set_user("Administrator")
	pairs = _pairs()
	before = _hashes(pairs)
	for k, v in before.items():
		print("B", " | ".join(k), "|", v)
	if not apply:
		print("N", len(before), "DRY")
		return

	print("SWITCHES ADDED", _enable_switches(site))
	from yht_custom import meeting_1027 as m

	for step in (
		m.setup_other_remarks_hidden,
		m.setup_cash_hides_due_date,
		m.setup_company_tax_id_hidden,
		m.setup_attention_hidden,
		m.setup_no_quick_customer,
	):
		print("STEP", step.__name__, step())
	frappe.db.commit()
	frappe.clear_cache()

	after = _hashes(pairs)
	# An error that was already there before is not ours; a NEW error or any changed hash is.
	diffs = [k for k in pairs if before[k] != after[k]]
	for k in diffs:
		print("DIFF", " | ".join(k), "|", before[k], "->", after[k])
	print("N", len(after), "DIFF", len(diffs))
	frappe.destroy()


if __name__ == "__main__":
	main(sys.argv[1], "--apply" in sys.argv)
