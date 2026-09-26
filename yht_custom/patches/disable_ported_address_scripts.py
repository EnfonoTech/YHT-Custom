# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""CR-001 — retire the two ad-hoc Address Client Scripts this app now ships.

`public/js/address.js` is a port of two Client Script records written on the live
site by another developer:

    Get SPL Full Address   adds the button that opens maps.splonline.com.sa
    Address Fetching       splits a pasted national address into the fields

The client offered the merge themselves — "if you want we can merge it into the
code". The reason to take it is that a record which exists only in a database is
invisible to review, to the test suite and to the next site.

🔴 BOTH REGISTER ON `Address.refresh`, SO THEY CANNOT COEXIST WITH THE PORT. Left
enabled, the form grows TWO "Get SPL Full Address" buttons and runs the parser
twice on one paste. This patch is therefore paired with the feature switch: it
disables the records on exactly the sites where `cr_001_spl_address` is on, which
is the same condition `address.js` checks before doing anything. Wherever the
switch is off, the Client Scripts keep working and the port stays inert — nothing
changes at all.

⚠️ DISABLED, NOT DELETED. They are another developer's work and the client is
still using them on production. `enabled = 0` is one column and one click to
reverse; `frappe.delete_doc` is neither.
"""

import frappe

from yht_custom import features

PORTED = ("Get SPL Full Address", "Address Fetching")


def execute():
	if not features.enabled("cr_001_spl_address"):
		print("  skipped — cr_001_spl_address is off for this site; the Client Scripts stay live")
		return

	disabled = []
	for name in PORTED:
		if not frappe.db.exists("Client Script", name):
			continue
		if not frappe.db.get_value("Client Script", name, "enabled"):
			continue
		# A document save, not `db.set_value`: `ClientScript.on_update` is what
		# clears the cached script bundle, and without it the desk keeps serving
		# the old one until the next restart.
		doc = frappe.get_doc("Client Script", name)
		doc.enabled = 0
		doc.save(ignore_permissions=True)
		disabled.append(name)

	frappe.db.commit()
	print(f"  disabled (superseded by yht_custom/public/js/address.js): {disabled or 'nothing — already off'}")
