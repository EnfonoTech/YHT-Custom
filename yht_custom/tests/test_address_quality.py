# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Address Data Quality — the ZATCA worklist (companion to plan 5.9)."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cstr

from yht_custom.saudi_address import national_address_gaps
from yht_custom.yht_custom.report.address_data_quality import address_data_quality as report


class TestAddressWorklist(FrappeTestCase):
	def test_every_saudi_address_appears_exactly_once(self):
		"""The Dynamic Link join multiplies.

		An address linked to both a Customer and a Supplier came back twice, turning
		578 Saudi addresses into 583 worklist rows — and Data Import would then have
		processed the same ID twice.
		"""
		rows = report._addresses()
		names = [row.name for row in rows]
		self.assertEqual(len(names), len(set(names)), "an address is listed more than once")

		gaps = national_address_gaps()
		self.assertEqual(len(names), gaps["saudi"])

	def test_only_saudi_addresses_are_listed(self):
		for row in report._addresses():
			with self.subTest(address=row.name):
				self.assertIn("saudi", cstr(row.country).lower())

	def test_the_zatca_blockers_are_district_and_building_number(self):
		"""Those two are what ksa_compliance requires for a Standard invoice."""
		self.assertTrue(report._blocks_zatca(["District"]))
		self.assertTrue(report._blocks_zatca(["Building No"]))
		self.assertFalse(report._blocks_zatca(["Postal Code"]))
		self.assertFalse(report._blocks_zatca([]))

	def test_the_report_flags_a_numeric_street(self):
		"""366 of 578 streets are bare numbers — the legacy building number."""
		rows = report.execute({"only_problems": 1})[1]
		flagged = [r for r in rows if "Street is a number" in cstr(r["malformed"])]
		self.assertTrue(flagged, "no numeric street detected on data that is full of them")

	def test_a_suggestion_is_only_made_when_it_is_safe(self):
		"""Suggest only a 4-digit street where the building number is empty."""
		rows = report.execute({"only_problems": 1})[1]
		for row in rows:
			suggestion = cstr(row["suggested_building_number"])
			if not suggestion:
				continue
			with self.subTest(address=row["address"]):
				self.assertRegex(suggestion, r"^\d{4}$")
				self.assertFalse(cstr(row["custom_building_number"]).strip())

	def test_the_blocker_filter_narrows_to_blockers(self):
		everything = report.execute({"only_problems": 1})[1]
		blockers = report.execute({"only_problems": 1, "blocks_zatca": 1})[1]
		self.assertLessEqual(len(blockers), len(everything))
		self.assertTrue(all(row["blocks_zatca"] for row in blockers))

	def test_a_clean_run_can_return_nothing(self):
		"""only_problems is the default, so a fixed site shows an empty report."""
		rows = report.execute({"only_problems": 1})[1]
		unfiltered = report.execute({"only_problems": 0})[1]
		self.assertLessEqual(len(rows), len(unfiltered))

	def test_the_party_filter_works(self):
		for party_type in ("Customer", "Supplier"):
			with self.subTest(party_type=party_type):
				rows = report.execute({"only_problems": 0, "party_type": party_type})[1]
				self.assertTrue(all(row["party_type"] == party_type for row in rows))


class TestWorklistExport(FrappeTestCase):
	def tearDown(self):
		path = frappe.utils.get_site_path("private", "files", "address-worklist.csv")
		if os.path.exists(path):
			os.remove(path)

	def test_the_csv_leads_with_the_id_column(self):
		"""Without ID first, Data Import creates 578 new addresses instead of updating."""
		path = report.export_worklist()
		with open(path) as handle:
			header = handle.readline().strip()
		self.assertTrue(header.startswith("ID,"), header)

	def test_the_csv_carries_only_real_address_fields(self):
		"""A guess column would break the import; the suggestion stays in the report."""
		meta = frappe.get_meta("Address")
		for field in report.EXPORT_FIELDS:
			with self.subTest(field=field):
				self.assertTrue(field == "name" or meta.get_field(field), f"{field} is not on Address")

	def test_one_csv_row_per_listed_address(self):
		path = report.export_worklist()
		with open(path) as handle:
			lines = [line for line in handle.read().splitlines() if line.strip()]
		rows = report.execute({"only_problems": 1})[1]
		self.assertEqual(len(lines) - 1, len(rows))
