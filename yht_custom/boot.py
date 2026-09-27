# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Session boot overrides for restricted branch users."""

import frappe

from yht_custom import features, list_defaults

#: Roles that get the trimmed desk. Anything holding an admin role is exempt.
RESTRICTED_ROLES = ("Branch User", "Stock User")
BYPASS_ROLES = ("System Manager", "Stock Manager", "Administrator")

DASHBOARD_ROUTE = "yht-dashboard"


def boot_session(bootinfo):
	"""Pin branch users to the dashboard and trim their sidebar."""
	# 🔴 ABOVE THE EARLY RETURNS, DELIBERATELY. Client sheet item 35 opens every
	# transaction list on the current fiscal year, and `public/js/list_defaults.js`
	# reads the answer straight out of `frappe.boot` because
	# `list_view.js::setup_defaults` builds the list synchronously and has no
	# moment to fetch it. Set below the Administrator / bypass-role returns it
	# would reach branch users only, and a manager's lists would silently keep
	# showing every year ever imported.
	#
	# 🔴 AND THEREFORE WRAPPED. Being above the early returns puts this on the boot
	# path of EVERY session, Guest included — so anything it raises 500s `/login`
	# for everybody, not just the branch users item 35 was written for.
	# `fiscal_year.resolve` guards its own `get_fiscal_year` call but its
	# `from erpnext.accounts.utils import …` sits OUTSIDE that try, so a partial
	# migrate or a half-installed erpnext raises ImportError straight through.
	# A missing fiscal year must never be the reason a site cannot be logged into;
	# `list_defaults.js` already treats an empty value as "set no filter".
	try:
		bootinfo.yht_current_fiscal_year = list_defaults.current_fiscal_year()
	except Exception:
		bootinfo.yht_current_fiscal_year = ""
		frappe.log_error(frappe.get_traceback(), "YHT boot: current fiscal year")

	# 🔴 SAME PLACE, SAME REASON. `features.active()` is how desk JS finds out
	# which site it is on — this bench serves the live site and UAT off ONE
	# `apps/yht_custom`, so a script file cannot know on its own. Above the early
	# returns because a feature is a property of the SITE, not of the user, and
	# wrapped for the same reason the line above it is: nothing on the boot path
	# may be the reason `/login` 500s.
	try:
		bootinfo.yht_features = features.active()
	except Exception:
		bootinfo.yht_features = []
		frappe.log_error(frappe.get_traceback(), "YHT boot: feature switches")

	# 🔴 CR-006 ACCEPTANCE #2 — "confirm the warehouse PICKER is scoped to the
	# branch, not just the saved value". The `before_validate` handler corrects the
	# value AFTER the operator has chosen; on its own that means the dropdown still
	# offers every warehouse on the site and the correction looks like the form
	# fighting them. The picker needs the list client-side, and `set_query` runs
	# while the form is being built — so it comes from boot, like the switches.
	#
	# Empty for a bypass user or a user on no branch, which is the same "do not
	# guess" rule `branch_defaults._branch_series_rows` follows; `branch_defaults.js`
	# then applies no filter at all.
	try:
		bootinfo.yht_branch_warehouses = _branch_warehouses_for_boot()
	except Exception:
		bootinfo.yht_branch_warehouses = []
		frappe.log_error(frappe.get_traceback(), "YHT boot: branch warehouses")

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


def _branch_warehouses_for_boot() -> list:
	"""The warehouses this user's branch configures, or `[]`.

	`[]` means "offer everything", not "offer nothing" — see `branch_defaults.js`.
	"""
	from yht_custom import branch_defaults, features

	if not features.enabled("cr_006_branch_warehouse"):
		return []
	if branch_defaults._is_bypass():
		return []
	config = branch_defaults._user_branch_config()
	if not config:
		return []
	return branch_defaults._branch_warehouses(config)


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
