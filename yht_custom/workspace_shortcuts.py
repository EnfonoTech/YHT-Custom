# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Item 11 — "keep direct new create button all the transaction module".

Every shortcut on the Accounts / Buying / Selling workspaces opens a LIST today.
Getting to a blank document is List → New, on every module, every time. These add
a second shortcut per doctype that lands straight on the new form.

`Workspace Shortcut.doc_view` takes `New` (options are List / Report Builder /
Dashboard / Tree / New / Calendar / Kanban), so this needs no custom routing.

🔴 A WORKSPACE SHORTCUT IS TWO WRITES, NOT ONE. The `shortcuts` child table holds
the shortcut; the workspace's `content` JSON holds the LAYOUT, and it references
each shortcut **by label**. Adding the child row alone puts the shortcut nowhere —
the block simply does not render. That is the same trap that left `Home` and
`Buying` with dead "Record Expenses" shortcuts after Step 1.
"""

import json

import frappe

#: Workspace → the doctypes that deserve a direct New button, in the order the
#: client works through them.
NEW_SHORTCUTS = {
	"Selling": ["Quotation", "Sales Order", "Delivery Note", "Sales Invoice"],
	"Buying": ["Purchase Order", "Purchase Receipt", "Purchase Invoice"],
	"Accounting": ["Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry"],
}

#: Filtered-LIST shortcuts. A return is a different document to an accountant — it carries
#: its own KSCN- series (for a branch user) — so it gets its own way in.
#:
#: 🔴 IT CANNOT BE A `doc_view: "New"` SHORTCUT. `Sales Invoice.is_return` is `no_copy = 1`
#: and `create_new.js` skips no_copy fields when applying `frappe.route_options`, so a
#: shortcut (or a URL, or a #hash — all measured) lands on a blank invoice with the box
#: CLEAR. Only setting it after the form exists works, and a Workspace Shortcut is config,
#: not code. So the shortcut opens the filtered LIST, and `sales_flow.js` puts a
#: "New Return" button on that list which ticks the box properly.
FILTERED_SHORTCUTS = {
	"Selling": [("Sales Invoice", "Sales Returns", {"is_return": 1})],
	"Accounting": [("Sales Invoice", "Sales Returns", {"is_return": 1})],
}

LABEL = "New {0}"


def setup_new_shortcuts() -> dict:
	"""Idempotent. Only ever ADDS — never reorders or removes what is there."""
	added, already, skipped = 0, 0, []

	for workspace, doctypes in NEW_SHORTCUTS.items():
		if not frappe.db.exists("Workspace", workspace):
			skipped.append(f"{workspace}: no such workspace")
			continue

		doc = frappe.get_doc("Workspace", workspace)
		existing = {row.label for row in doc.shortcuts}
		content = _load_content(doc)
		changed = False

		for doctype in doctypes:
			if not frappe.db.exists("DocType", doctype):
				skipped.append(f"{workspace}: no doctype {doctype}")
				continue

			label = LABEL.format(doctype)
			if label in existing:
				already += 1
			else:
				doc.append(
					"shortcuts",
					{
						"type": "DocType",
						"link_to": doctype,
						"doc_view": "New",
						"label": label,
						"color": "Green",
					},
				)
				changed = True
				added += 1

			# The layout half. Without this the shortcut exists and shows nowhere.
			if not _content_has(content, label):
				content.append({"id": f"yht-{label.lower().replace(' ', '-')}",
				                "type": "shortcut",
				                "data": {"shortcut_name": label, "col": 3}})
				changed = True

		for doctype, label, filters in FILTERED_SHORTCUTS.get(workspace, []):
			if not frappe.db.exists("DocType", doctype):
				skipped.append(f"{workspace}: no doctype {doctype}")
				continue
			if label in existing:
				already += 1
			else:
				doc.append(
					"shortcuts",
					{
						"type": "DocType",
						"link_to": doctype,
						"doc_view": "List",
						"stats_filter": json.dumps(filters),
						"label": label,
						"color": "Orange",
					},
				)
				changed = True
				added += 1
			if not _content_has(content, label):
				content.append({"id": f"yht-{label.lower().replace(' ', '-')}",
				                "type": "shortcut",
				                "data": {"shortcut_name": label, "col": 3}})
				changed = True

		if changed:
			doc.content = json.dumps(content)
			doc.flags.ignore_permissions = True
			doc.flags.ignore_links = True
			doc.save()

	if skipped:
		frappe.log_error("\n".join(skipped), "yht_custom: new-create shortcuts")

	return {"added": added, "already": already, "skipped": skipped}


def _load_content(doc) -> list:
	try:
		return json.loads(doc.content or "[]")
	except (ValueError, TypeError):
		return []


def _content_has(content, label) -> bool:
	for block in content:
		if not isinstance(block, dict):
			continue
		if block.get("type") != "shortcut":
			continue
		if (block.get("data") or {}).get("shortcut_name") == label:
			return True
	return False
