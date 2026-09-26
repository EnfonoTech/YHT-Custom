# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""CR-020 — the report list, grouped the way the client asked for it.

Client's words: "clutter… group-wise… stock related in one group, sales statement
related in one group".

## The mechanism already exists; the grouping was ours, not theirs

`KATC Reports` is a public Workspace in module `Yht Custom` and it already uses
`Workspace Link` rows of type **Card Break** to make groups — measured
2026-09-26, it carried three: *Client Reports*, *Branch*, *Data & Go-Live*. So
nothing new has to be invented. What it grouped by was the project's own history
(which reports we wrote, which branch work needed) rather than by what the report
is FOR, which is what the client named.

This module rewrites those rows into the client's categories and folds in the
standard ERPNext reports they actually run, so the workspace is the answer to
"where is the stock report" rather than a second place to look after the Reports
list.

🔴 A LINK TO A REPORT THAT DOES NOT EXIST BREAKS THE WHOLE WORKSPACE, not just
that row — `workspace.py` resolves every link on render. Every name below is
checked against the database first and a missing one is dropped silently, which
is why the standard-report names can be listed optimistically: a site without
`Item-wise Sales Register` simply does not show it.

⚠️ SHORTCUTS ARE NOT TOUCHED. The three at the top of the workspace are the
client's daily three and were placed deliberately; regrouping the links below
them is the whole of this item.
"""

import frappe

#: Ordered `(group label, [report names])`. The order IS the page order.
GROUPS = (
	(
		"Stock",
		(
			"KATC Stock Ledger",
			"Stock Ledger",
			"Stock Balance",
			"Stock Projected Qty",
			"Stock Valuation Snapshot",
		),
	),
	(
		"Sales Statements",
		(
			"Customer Statement",
			"Stock Sales",
			"Sales Register",
			"Item-wise Sales Register",
			"Sales Order Analysis",
			"Delivery Note Item Note Linked",
			"Pending Delivery Note Customer wise",
		),
	),
	(
		"Receivables & Collection",
		(
			"Branch Receivables",
			"Collection",
			"Accounts Receivable",
			"Accounts Receivable Summary",
		),
	),
	(
		"Ledgers",
		(
			"KATC General Ledger",
			"KATC Party and Account Ledger",
			"General Ledger",
			"Trial Balance",
		),
	),
	(
		"Purchase",
		("Purchase Register", "Item-wise Purchase Register", "Accounts Payable"),
	),
	(
		"Data & Go-Live",
		("Import Gate", "Address Data Quality"),
	),
)

WORKSPACE = "KATC Reports"


def _existing(names) -> list:
	"""The reports on this site, in the declared order."""
	present = set(
		frappe.get_all("Report", filters={"name": ["in", list(names)]}, pluck="name")
	)
	return [name for name in names if name in present]


def setup_report_groups() -> dict:
	"""Rewrite the workspace's links into the client's categories. Idempotent."""
	if not frappe.db.exists("Workspace", WORKSPACE):
		return {"skipped": f"{WORKSPACE} does not exist"}

	rows = []
	for label, names in GROUPS:
		reports = _existing(names)
		if not reports:
			continue
		rows.append({"type": "Card Break", "label": label, "hidden": 0, "onboard": 0})
		for report in reports:
			rows.append(
				{
					"type": "Link",
					"label": report,
					"link_type": "Report",
					"link_to": report,
					"hidden": 0,
					"onboard": 0,
					# Report Builder reports need the doctype to route correctly.
					"is_query_report": frappe.db.get_value("Report", report, "report_type")
					in ("Query Report", "Script Report"),
				}
			)

	if not rows:
		return {"skipped": "no reports resolved"}

	doc = frappe.get_doc("Workspace", WORKSPACE)

	current = [
		(link.type, link.label, link.link_to) for link in doc.links
	]
	wanted = [(row["type"], row["label"], row.get("link_to")) for row in rows]
	if current == wanted:
		# 🔴 COMPARED BEFORE SAVING. `after_migrate` runs this on every deploy, and
		# a workspace rewritten every time floods the Version table and reorders
		# the page under anyone who has it open.
		return {"unchanged": True, "groups": [label for label, _ in GROUPS]}

	doc.links = []
	for row in rows:
		doc.append("links", row)
	doc.save(ignore_permissions=True)

	return {"groups": [row["label"] for row in rows if row["type"] == "Card Break"], "links": len(rows)}
