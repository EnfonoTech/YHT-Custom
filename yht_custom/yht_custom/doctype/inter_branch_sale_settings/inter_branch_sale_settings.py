# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Settings for Inter Branch Sale: the accounts, the defaults and the customers allowed.

Everything the posting needs lives here and nothing is a constant in the code, because the accounts are
the client's accountant's decision. `gaps()` names what is still missing; the sale refuses to submit
while any gap is open.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr

#: fieldname -> label, every account the posting needs.
REQUIRED = {
	"company": "Company",
	"receivable_account": "Receivable Account",
	"cogs_account": "Cost of Goods Sold Account",
	"income_account": "Sales Income Account",
	"cost_center": "Cost Center",
}


class InterBranchSaleSettings(Document):
	def validate(self):
		self._check_accounts()
		seen = set()
		for row in self.customers or []:
			if row.customer in seen:
				frappe.throw(_("Row {0}: customer {1} is listed twice.").format(row.idx, row.customer))
			seen.add(row.customer)

	def _check_accounts(self):
		"""Only what is set is checked; an empty field is a gap, not an error, until a sale is submitted."""
		company = self.company
		checks = (
			("receivable_account", {"account_type": "Receivable", "is_group": 0}, _("must be a Receivable account")),
			("cogs_account", {"root_type": "Expense", "is_group": 0}, _("must be an Expense account")),
			("income_account", {"root_type": "Income", "is_group": 0}, _("must be an Income account")),
		)
		for field, filters, message in checks:
			name = self.get(field)
			if not name:
				continue
			row = frappe.db.get_value("Account", name, ["company", "account_type", "root_type", "is_group", "disabled"], as_dict=True)
			if not row:
				frappe.throw(_("{0} {1} does not exist.").format(_(REQUIRED[field]), name))
			if company and row.company != company:
				frappe.throw(_("{0} {1} belongs to {2}, not {3}.").format(_(REQUIRED[field]), name, row.company, company))
			if row.disabled:
				frappe.throw(_("{0} {1} is disabled.").format(_(REQUIRED[field]), name))
			for key, expected in filters.items():
				got = row.get(key)
				ok = got in expected[1] if isinstance(expected, list) else got == expected
				if not ok:
					frappe.throw(_("{0} {1} {2}.").format(_(REQUIRED[field]), name, message))


def gaps(settings=None) -> list:
	"""The labels of what is still unset, in the order the settings page shows them."""
	settings = settings or frappe.get_cached_doc("Inter Branch Sale Settings")
	missing = [label for field, label in REQUIRED.items() if not cstr(settings.get(field)).strip()]
	if not [row for row in settings.get("customers") or [] if row.customer]:
		missing.append("Inter-Branch Customers")
	return missing


def allowed_customers() -> list:
	settings = frappe.get_cached_doc("Inter Branch Sale Settings")
	return [row.customer for row in settings.get("customers") or [] if row.customer]
