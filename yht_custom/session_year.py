# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Row 26 (meeting 2026-10-11) — the Session-Defaults fiscal year drives the list filters.

A soft default, not a permission. Session Default Settings lives in FRAPPE CORE (not
ERPNext): `set_session_default_values` calls `frappe.defaults.set_user_default` for each
key, and the `on_logout` hook (`clear_session_defaults`) clears only keys that have a row
in Session Default Settings — so every login starts with no chosen year (a pop-up per
login is the right shape) and the `Fiscal Year` row must exist or a chosen year would
survive logout forever (`setup_session_year`).

🔴 A LIST DEFAULT ALONE NEVER REACHES A USER WHO HAS OPENED THE LIST. `list_view.js`
prefers SAVED filters over `listview_settings[dt].filters`, and `before_render` saves the
current filters on every render — so today's default becomes a saved filter the first
time a list is opened. `sync_saved_filters` therefore rewrites the saved
`custom_fiscal_year` clause to the chosen year when boot is recomputed (which happens right
after `set_user_default` clears that user's boot cache, i.e. once per change).

The user's OWN default rows are read (`get_defaults_for(user)`), never `get_user_default`,
which merges global defaults over them — a future global `fiscal_year` key must not
masquerade as a choice.
"""

import json

import frappe
from frappe.utils import cint, cstr

from yht_custom import features, fiscal_year


def chosen_year(user=None) -> str:
	"""The Fiscal Year this user chose for the session, or `""`.

	`""` when the switch is off, when nothing was chosen, or when the choice is missing or
	disabled (D7): the caller then falls back to the current year.
	"""
	if not features.enabled("oct11_r26_session_fiscal_year"):
		return ""
	own = frappe.defaults.get_defaults_for(user or frappe.session.user) or {}
	year = own.get("fiscal_year")
	if isinstance(year, (list, tuple)):
		year = year[0] if year else ""
	year = cstr(year).strip()
	if not year:
		return ""
	disabled = frappe.db.get_value("Fiscal Year", year, "disabled")
	if disabled is None or cint(disabled):
		return ""
	return year


def fiscal_year_choices() -> list:
	"""Enabled Fiscal Years, newest first."""
	return frappe.get_all(
		"Fiscal Year", filters={"disabled": 0}, order_by="year_start_date desc", pluck="name"
	)


def boot_value() -> dict:
	"""`bootinfo.yht_session_year` — `{}` when the switch is off."""
	if not features.enabled("oct11_r26_session_fiscal_year"):
		return {}
	user = frappe.session.user
	if user == "Guest":
		return {}

	from yht_custom import list_defaults

	year = chosen_year(user)
	if year:
		sync_saved_filters(user, year)
	return {
		"enabled": True,
		"choices": fiscal_year_choices(),
		"current": list_defaults.default_fiscal_year(),
		# Prompt until the user has a usable choice of their own.
		"needs_prompt": not year,
		"companies": frappe.get_all("Company", pluck="name"),
	}


def sync_saved_filters(user, year) -> None:
	"""Rewrite each fiscal-year list's saved year clause to `year`. Never raises.

	Only the SESSION user's settings are reachable through frappe's user-settings API, and
	nothing is written unless a clause actually changes. A list with no year clause is left
	alone (the user chose all years). `__UserSettings` rows are never written directly: the
	`_user_settings` cache hash would overwrite them.
	"""
	try:
		if not year or user != frappe.session.user:
			return
		from frappe.model.utils import user_settings

		for doctype in fiscal_year.DATE_FIELD:
			try:
				current = json.loads(user_settings.get_user_settings(doctype))
				listing = current.get("List") if isinstance(current, dict) else None
				filters = listing.get("filters") if isinstance(listing, dict) else None
				if not isinstance(filters, list):
					continue
				changed = False
				for clause in filters:
					if (
						isinstance(clause, list)
						and len(clause) >= 4
						and clause[1] == fiscal_year.FIELDNAME
						and clause[2] == "="
						and clause[3] != year
					):
						clause[3] = year
						changed = True
				if changed:
					user_settings.update_user_settings(doctype, {"List": listing})
			except Exception:
				frappe.log_error(title="YHT session year: saved filters", message=frappe.get_traceback())
	except Exception:
		frappe.log_error(title="YHT session year: saved filters", message=frappe.get_traceback())


def setup_session_year() -> dict:
	"""Row 26 provisioning. Idempotent, no commit.

	1. `Session Default Settings` has a `Fiscal Year` row (present on both sites today;
	   the step exists so a re-seeded UAT cannot regress).
	2. **Branch roles may READ Fiscal Year.** Found by the browser pass, not by a test:
	   the lists' Fiscal Year filter is a LINK control, a Link control validates its value
	   through `frappe.client.validate_link`, and without read on the target a branch user
	   gets "You do not have Read or Select Permissions for Fiscal Year" the moment a list
	   opens with the default year set — and the filter is never applied. The default year
	   (item 35) therefore never worked for the people it was written for.

	   The grant follows the app's own rule for a doctype that gains a Custom DocPerm
	   (gotcha 6): a Custom DocPerm row REPLACES the standard permissions of the whole
	   doctype, so the standard rows are mirrored first — exactly what
	   `setup.preserve_standard_docperms` does for every doctype in
	   `BRANCH_USER_PERMISSIONS`. Fiscal Year is deliberately NOT added to that list: this
	   is behind the row-26 switch, that list is not.
	"""
	if not features.enabled("oct11_r26_session_fiscal_year"):
		return {"skipped": "oct11_r26_session_fiscal_year is off for this site"}

	out = {}
	settings = frappe.get_single("Session Default Settings")
	if any(row.ref_doctype == "Fiscal Year" for row in settings.session_defaults):
		out["session_row"] = "already"
	else:
		settings.append("session_defaults", {"ref_doctype": "Fiscal Year"})
		settings.flags.ignore_permissions = True
		settings.save()
		out["session_row"] = "added"

	out["fiscal_year_read"] = _grant_fiscal_year_read()
	return out


def _grant_fiscal_year_read() -> dict:
	from yht_custom.setup import (
		BRANCH_MANAGER_ROLE,
		BRANCH_USER_ROLE,
		PERM_FIELDS,
		_upsert_custom_docperm,
	)

	if not frappe.db.exists("DocType", "Fiscal Year"):
		return {}

	mirrored = 0
	if not frappe.db.exists("Custom DocPerm", {"parent": "Fiscal Year"}):
		for row in frappe.get_all(
			"DocPerm", filters={"parent": "Fiscal Year"}, fields=["role", "permlevel", *PERM_FIELDS]
		):
			_upsert_custom_docperm("Fiscal Year", row.role, row, permlevel=row.permlevel)
			mirrored += 1

	for role in (BRANCH_USER_ROLE, BRANCH_MANAGER_ROLE):
		_upsert_custom_docperm("Fiscal Year", role, {"read": 1, "select": 1, "report": 1})
	frappe.clear_cache(doctype="Fiscal Year")
	return {"mirrored": mirrored, "roles": [BRANCH_USER_ROLE, BRANCH_MANAGER_ROLE]}
