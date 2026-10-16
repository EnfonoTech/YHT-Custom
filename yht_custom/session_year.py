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
from frappe import _
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


def year_range(year):
	"""`(start, end)` ISO dates of a Fiscal Year, or `None`."""
	row = frappe.db.get_value("Fiscal Year", year, ["year_start_date", "year_end_date"], as_dict=True)
	if not row or not row.year_start_date or not row.year_end_date:
		return None
	return (str(row.year_start_date), str(row.year_end_date))


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
	limit = None
	if year and features.enabled("oct15_r26_new_document_year"):
		limit = year_range(year)
	return {
		"enabled": True,
		# The chosen year's dates, when new documents must stay inside it (row 26, "new also"):
		# `{start, end, date_fields}` for `public/js/session_year.js`; `None` otherwise.
		"limit": {"start": limit[0], "end": limit[1], "date_fields": fiscal_year.DATE_FIELD} if limit else None,
		"choices": fiscal_year_choices(),
		"current": list_defaults.default_fiscal_year(),
		# Prompt until the user has a usable choice of their own.
		"needs_prompt": not year,
		"companies": frappe.get_all("Company", pluck="name"),
	}


def sync_saved_filters(user, year, add_missing=False) -> None:
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
				has_clause = False
				for clause in filters:
					if isinstance(clause, list) and len(clause) >= 4 and clause[1] == fiscal_year.FIELDNAME and clause[2] == "=":
						has_clause = True
						if clause[3] != year:
							clause[3] = year
							changed = True
				# 🔴 THE CASE THE CLIENT HIT (2026-10-16: "I choose 2025 at login and the lists still show
				# 2026"). A user whose list was opened BEFORE the year default existed — or who removed the
				# clause — carries saved filters with no year in them, and `list_view.js` prefers saved
				# filters over our default, so the chosen year never reached the list. When the user
				# CHOOSES a year (`add_missing`, from `apply_chosen_year`) the clause is added to a
				# non-empty saved set; at plain boot it is still left alone, so a user who removes it
				# afterwards keeps "all years" until they choose again.
				if add_missing and not has_clause and filters:
					filters.append([doctype, fiscal_year.FIELDNAME, "=", year])
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


def enforce_new_document_year(doc, method=None):
	"""`before_insert` — a NEW document must be dated inside the fiscal year chosen for the session.

	Client, 2026-10-15 ("26 - new also"): choosing a year hides the other years' documents from the
	lists (the filter) AND stops a new document from being dated in another one. This is the
	boundary; the form's date picker is only the courtesy that keeps the operator from reaching it.

	Not applied to: an amendment (it keeps its original document's date), an import or a patch, a
	user who has chosen no year (nothing is enforced for them), a document without its date field.
	A background job runs as a user with no chosen year, so it is never stopped. Behind
	`oct15_r26_new_document_year` on top of the row-26 switch.
	"""
	if not features.enabled("oct15_r26_new_document_year"):
		return
	if doc.get("amended_from") or frappe.flags.in_import or frappe.flags.in_patch:
		return
	date_field = fiscal_year.DATE_FIELD.get(doc.doctype)
	value = doc.get(date_field) if date_field else None
	if not value:
		return

	year = chosen_year()
	if not year:
		return
	limits = year_range(year)
	if not limits:
		return

	from frappe.utils import formatdate, getdate

	if not (getdate(limits[0]) <= getdate(value) <= getdate(limits[1])):
		frappe.throw(
			_("{0} {1} is outside the fiscal year you selected ({2}: {3} to {4}). Choose that year's date, or change the fiscal year in Session Defaults.").format(
				_(doc.meta.get_label(date_field)),
				formatdate(value),
				year,
				formatdate(limits[0]),
				formatdate(limits[1]),
			),
			title=_("Date outside the selected fiscal year"),
		)


def apply_chosen_year(default_values=None):
	"""`set_session_default_values`, plus: the chosen year reaches the saved list filters.

	Frappe's own method (the avatar menu's Session Defaults dialog AND our login pop-up both call it)
	stores the choice and clears the user's cache. This wraps it through `override_whitelisted_methods`
	(honoured by `handler.execute_cmd`, which is how both dialogs reach it) and, when the call carries a
	`fiscal_year`, adds the year clause to the saved list filters that lack one. Behind the row-26
	switch: with it off this is exactly Frappe's method.
	"""
	from frappe.core.doctype.session_default_settings.session_default_settings import (
		set_session_default_values as _frappe_method,
	)

	result = _frappe_method(default_values)
	if not features.enabled("oct11_r26_session_fiscal_year"):
		return result
	try:
		values = json.loads(default_values) if isinstance(default_values, str) else (default_values or {})
		year = cstr(values.get("fiscal_year")).strip()
		if year and result == "success" and frappe.db.get_value("Fiscal Year", year, "disabled") is not None:
			sync_saved_filters(frappe.session.user, year, add_missing=True)
	except Exception:
		frappe.log_error(title="YHT session year: apply chosen year", message=frappe.get_traceback())
	return result
