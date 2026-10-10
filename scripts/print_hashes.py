"""sha256 of every enabled KATC print, on the newest submitted document of its doctype.

The before/after check of every deploy (CLAUDE.md gotcha 107). Run from the bench's
`sites/` directory as the bench user — `frappe.init` needs an absolute `sites_path`
(gotcha 117):

    cd /home/v15/yht-bench/sites
    sudo -u v15 -H ../env/bin/python /path/to/print_hashes.py yht-khobhar.enfonoerp.com

🔴 ASSERT THE COUNT, NOT JUST THE DIFF. On 2026-10-10 a `bench console` heredoc
version of this printed nothing, both before and after, and `diff` of two empty files
reported "PRINTS IDENTICAL (0 formats)" — a pass that proved nothing. The last line is
`N <count>`; a deploy script must refuse anything but the expected number.
"""

import hashlib
import os
import sys

import frappe


def main(site: str) -> int:
	frappe.init(site=site, sites_path=os.getcwd())
	frappe.connect()
	formats = frappe.get_all(
		"Print Format",
		filters={"disabled": 0, "name": ["like", "KATC%"]},
		fields=["name", "doc_type"],
	)
	n = 0
	for fmt in sorted(formats, key=lambda f: f.name):
		name = frappe.db.get_value(fmt.doc_type, {"docstatus": 1}, "name", order_by="modified desc")
		if not name:
			print("H", fmt.name, "| no submitted document |")
			continue
		html = frappe.get_print(fmt.doc_type, name, fmt.name)
		print("H", fmt.name, "|", name, "|", hashlib.sha256(html.encode()).hexdigest()[:16])
		n += 1
	print("N", n)
	# `frappe.get_print` commits (gotcha 84); nothing here writes, but be explicit.
	frappe.db.rollback()
	return n


if __name__ == "__main__":
	main(sys.argv[1])
