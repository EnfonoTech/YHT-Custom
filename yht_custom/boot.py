# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Session boot overrides for restricted branch users."""

import frappe

#: Roles that get the trimmed desk. Anything holding an admin role is exempt.
RESTRICTED_ROLES = ("Branch User", "Stock User")
BYPASS_ROLES = ("System Manager", "Stock Manager", "Administrator")

DASHBOARD_ROUTE = "yht-dashboard"


def boot_session(bootinfo):
	"""Pin branch users to the dashboard and trim their sidebar."""
	user = frappe.session.user
	if user in ("Administrator", "Guest"):
		return

	roles = set(frappe.get_roles(user))
	if roles & set(BYPASS_ROLES):
		return
	if not roles & set(RESTRICTED_ROLES):
		return

	bootinfo.default_route = DASHBOARD_ROUTE
	bootinfo.allowed_modules = ["Yht Custom"]
	bootinfo.allowed_workspaces = [{"name": "Branch User"}]
	bootinfo.yht_branch_restricted = True

	_pin_default_company(bootinfo, user)


def _pin_default_company(bootinfo, user):
	"""Force the user's own company into the session defaults.

	Global Defaults may name a company this user has no permission for, which
	makes every new form fail on the company link instead of prefilling it.
	"""
	company = frappe.db.get_value(
		"User Permission", {"user": user, "allow": "Company", "is_default": 1}, "for_value"
	)
	if not company:
		return

	bootinfo.yht_default_company = company

	if bootinfo.get("sysdefaults"):
		bootinfo.sysdefaults["company"] = company

	if not bootinfo.get("user"):
		bootinfo.user = frappe._dict()
	defaults = bootinfo.user.get("defaults") if isinstance(bootinfo.user, dict) else None
	if isinstance(defaults, dict):
		# Frappe reads both casings depending on the call site.
		defaults["company"] = company
		defaults["Company"] = company
