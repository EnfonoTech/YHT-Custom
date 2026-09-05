# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Checks 35-40 — the derived fiscal year."""

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import fiscal_year
from yht_custom.fiscal_year import DATE_FIELD, FIELDNAME


class TestFiscalYear(FrappeTestCase):
	def test_every_registered_doctype_has_a_date_field_mapping(self):
		"""check 35 — `hooks.py` and `DATE_FIELD` must name the same doctypes. If a
		doctype is hooked but unmapped the handler silently does nothing; if it is
		mapped but unhooked the field never fills."""
		hooked = {
			doctype
			for doctype, events in frappe.get_hooks("doc_events").items()
			if any(
				"yht_custom.fiscal_year.set_fiscal_year" in (h if isinstance(h, list) else [h])
				for h in events.values()
			)
		}
		self.assertEqual(hooked, set(DATE_FIELD))

	def test_the_date_field_named_for_each_doctype_actually_exists(self):
		# check 36 — a typo here files documents under no year at all.
		for doctype, date_field in DATE_FIELD.items():
			self.assertTrue(
				frappe.get_meta(doctype).get_field(date_field),
				f"{doctype} has no field {date_field}",
			)

	def test_the_field_exists_and_is_a_list_view_filter(self):
		# check 37 — the whole point is filtering, so the flag is part of the contract.
		for doctype in DATE_FIELD:
			f = frappe.get_meta(doctype).get_field(FIELDNAME)
			if not f:
				self.skipTest(f"{FIELDNAME} not provisioned on {doctype} yet")
			self.assertEqual(f.fieldtype, "Link")
			self.assertEqual(f.options, "Fiscal Year")
			self.assertTrue(f.in_standard_filter, f"{doctype}: not a standard filter")

	def test_the_field_never_carries_a_fixed_default(self):
		"""check 38 — the client's previous system defaulted this to `2026`, which is
		why 731 migrated invoices claim FY 2026 while dated 2024. A default here would
		reproduce exactly that, and it would look authoritative."""
		for doctype in DATE_FIELD:
			f = frappe.get_meta(doctype).get_field(FIELDNAME)
			if not f:
				continue
			self.assertFalse(f.default, f"{doctype}: {FIELDNAME} has a fixed default")

	def test_resolve_matches_the_year_that_contains_the_date(self):
		# check 39
		for fy in frappe.get_all(
			"Fiscal Year", fields=["name", "year_start_date", "year_end_date", "disabled"]
		):
			got = fiscal_year.resolve(fy.year_start_date, include_disabled=True)
			self.assertEqual(got, fy.name, f"{fy.year_start_date} resolved to {got}")

	def test_a_disabled_year_is_reachable_only_for_the_backfill(self):
		"""check 40 — historical documents belong in their closed year, but a NEW
		document must never be filed into one."""
		disabled = frappe.get_all(
			"Fiscal Year", filters={"disabled": 1}, fields=["name", "year_start_date"], limit=1
		)
		if not disabled:
			self.skipTest("no disabled Fiscal Year on this site")
		date = disabled[0].year_start_date
		self.assertEqual(fiscal_year.resolve(date), "")
		self.assertEqual(fiscal_year.resolve(date, include_disabled=True), disabled[0].name)

	def test_a_missing_date_never_raises(self):
		# check 40b — an empty date must leave the field blank, not break the save.
		self.assertEqual(fiscal_year.resolve(None), "")
		self.assertEqual(fiscal_year.resolve(""), "")
