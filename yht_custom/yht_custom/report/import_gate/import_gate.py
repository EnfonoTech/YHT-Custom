# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Import Gate — the MoM acceptance test as a report finance can sign (plan 7.1).

Every row is one check with a verdict. A blocking row that is not PASS means
go-live does not proceed; see `yht_custom.import_gate` for what each check
measures and why.
"""

import frappe
from frappe import _

from yht_custom import import_gate


def execute(filters=None):
	rows = import_gate.run_checks()

	blocking_failures = [r for r in rows if r["blocking"] and r["status"] != "PASS"]
	verdict = _("GATE PASSES") if not blocking_failures else _(
		"GATE FAILS — {0} blocking issue(s)"
	).format(len(blocking_failures))

	summary = [
		{
			"label": _("Verdict"),
			"value": verdict,
			"indicator": "Green" if not blocking_failures else "Red",
			"datatype": "Data",
		},
		{
			"label": _("Blocking failures"),
			"value": len(blocking_failures),
			"indicator": "Green" if not blocking_failures else "Red",
			"datatype": "Int",
		},
		{
			"label": _("Checks run"),
			"value": len(rows),
			"datatype": "Int",
		},
	]

	return _columns(), rows, None, None, summary


def _columns():
	return [
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 80},
		{"fieldname": "check", "label": _("Check"), "fieldtype": "Data", "width": 250},
		{"fieldname": "blocking", "label": _("Blocks Go-Live"), "fieldtype": "Check", "width": 110},
		{"fieldname": "measured", "label": _("Measured"), "fieldtype": "Data", "width": 300},
		{"fieldname": "difference", "label": _("Difference"), "fieldtype": "Float", "width": 130},
		{"fieldname": "detail", "label": _("Detail"), "fieldtype": "Data", "width": 340},
	]
