# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""HR module configuration (plan 6.8).

HR on this site is live — 13 employees, 191 salary slips, 797 attendance rows —
so every test here reads, and the module under test only ever creates what is
missing.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from yht_custom import hr_setup


class TestGosi(FrappeTestCase):
	def test_the_three_gosi_components_exist(self):
		"""There was no GOSI component of any kind. Social insurance is not optional."""
		for name in ("GOSI Wage", "GOSI Employee", "GOSI Employer"):
			with self.subTest(component=name):
				self.assertTrue(frappe.db.exists("Salary Component", name), f"{name} missing")

	def test_the_employee_share_is_a_deduction_at_the_statutory_rate(self):
		doc = frappe.get_doc("Salary Component", "GOSI Employee")
		self.assertEqual(doc.type, "Deduction")
		self.assertFalse(doc.statistical_component, "the employee share IS withheld")
		self.assertTrue(doc.amount_based_on_formula)
		self.assertIn(str(hr_setup.GOSI_EMPLOYEE_RATE), doc.formula)

	def test_the_employer_share_never_touches_net_pay(self):
		"""An employer contribution is a company cost, not a withholding."""
		doc = frappe.get_doc("Salary Component", "GOSI Employer")
		self.assertTrue(doc.statistical_component)
		self.assertIn(str(hr_setup.GOSI_EMPLOYER_RATE), doc.formula)
		self.assertIn(str(hr_setup.GOSI_NON_SAUDI_EMPLOYER_RATE), doc.formula)

	def test_the_employee_share_applies_to_saudi_nationals_only(self):
		doc = frappe.get_doc("Salary Component", "GOSI Employee")
		self.assertEqual(doc.condition.strip(), "custom_is_saudi_national")
		self.assertTrue(
			frappe.get_meta("Employee").get_field("custom_is_saudi_national"),
			"the condition names a field that does not exist, so it evaluates to nothing",
		)

	def test_the_formula_namespace_really_carries_employee_fields(self):
		"""hrms puts the whole Employee doc in the eval namespace.

		If that ever changes, `custom_is_saudi_national` in a condition silently
		stops matching and every Saudi employee stops contributing.
		"""
		import inspect

		from hrms.payroll.doctype.salary_slip import salary_slip

		source = inspect.getsource(salary_slip.SalarySlip.get_data_for_eval)
		self.assertIn("data.update(employee)", source)

	def test_the_wage_cap_is_applied(self):
		doc = frappe.get_doc("Salary Component", "GOSI Wage")
		self.assertIn(str(hr_setup.GOSI_WAGE_CAP), doc.formula)
		self.assertTrue(doc.statistical_component, "the wage base is not itself pay")


class TestLeaveTypes(FrappeTestCase):
	def test_the_saudi_labour_law_leave_types_exist(self):
		for spec in hr_setup.LEAVE_TYPES:
			with self.subTest(leave_type=spec["leave_type_name"]):
				self.assertTrue(frappe.db.exists("Leave Type", spec["leave_type_name"]))

	def test_the_sick_leave_tiers_match_article_117(self):
		"""30 days full, 60 at 75%, 30 unpaid."""
		tiers = {
			"Sick Leave Full Pay": (30, 0),
			"Sick Leave 75 Percent": (60, 0),
			"Sick Leave Unpaid": (30, 1),
		}
		for name, (days, is_lwp) in tiers.items():
			with self.subTest(leave_type=name):
				row = frappe.db.get_value("Leave Type", name, ["max_leaves_allowed", "is_lwp"], as_dict=True)
				self.assertEqual(row.max_leaves_allowed, days)
				self.assertEqual(int(row.is_lwp or 0), is_lwp)

	def test_annual_leave_carries_forward(self):
		row = frappe.db.get_value(
			"Leave Type", "Annual Leave", ["max_leaves_allowed", "is_carry_forward"], as_dict=True
		)
		self.assertEqual(row.max_leaves_allowed, 21)
		self.assertTrue(row.is_carry_forward)


class TestCalendarAndPeriod(FrappeTestCase):
	def test_this_year_has_a_holiday_list(self):
		"""The company default was `Standard Holiday 2025`, already expired."""
		year = getdate().year
		self.assertTrue(frappe.db.exists("Holiday List", hr_setup.holiday_list_name(year)))

	def test_the_holiday_list_carries_the_fixed_national_days(self):
		year = getdate().year
		name = hr_setup.holiday_list_name(year)
		descriptions = " ".join(
			frappe.get_all("Holiday", filters={"parent": name}, pluck="description") or []
		)
		self.assertIn("Founding Day", descriptions)
		self.assertIn("National Day", descriptions)

	def test_eid_is_never_invented(self):
		"""Eid is lunar. A wrong Eid changes payment days on every slip that month."""
		year = getdate().year
		name = hr_setup.holiday_list_name(year)
		descriptions = frappe.get_all("Holiday", filters={"parent": name}, pluck="description")
		generated = [text for text in descriptions if "eid" in (text or "").lower()]
		self.assertFalse(generated, "an Eid date was guessed rather than confirmed")

	def test_the_weekend_is_friday_and_saturday(self):
		year = getdate().year
		name = hr_setup.holiday_list_name(year)
		rows = frappe.get_all("Holiday", filters={"parent": name, "weekly_off": 1}, pluck="holiday_date")
		self.assertTrue(rows, "no weekly offs were generated")
		weekdays = {getdate(date).strftime("%A") for date in rows}
		self.assertEqual(weekdays, set(hr_setup.WEEKLY_OFF_DAYS))

	def test_this_year_has_a_payroll_period(self):
		"""The only period ended 2025-12-31."""
		year = getdate().year
		self.assertTrue(frappe.db.exists("Payroll Period", {"start_date": f"{year}-01-01"}))


class TestHrGuardrails(FrappeTestCase):
	def test_setup_is_idempotent(self):
		second = hr_setup.setup_hr()
		self.assertEqual(second["salary_components"]["created"], [])
		self.assertEqual(second["leave_types"]["created"], [])
		self.assertEqual(second["employee_fields"]["created"], 0)
		self.assertIn("existing", second["holiday_list"])
		self.assertIn("existing", second["payroll_period"])

	def test_no_existing_salary_structure_was_touched(self):
		"""13 structures are submitted and 191 slips reference their components."""
		self.assertEqual(frappe.db.count("Salary Structure", {"docstatus": 2}), 0)

	def test_the_gap_report_flags_the_placeholder_wage_base(self):
		"""The GOSI base ships as a placeholder ON PURPOSE and must say so loudly."""
		summary = hr_setup.hr_gaps()
		self.assertIn("gosi_wage_still_placeholder", summary)
		self.assertTrue(summary["gosi_wage_still_placeholder"])
		self.assertGreaterEqual(summary["employees_active"], 1)


class TestGapCounting(FrappeTestCase):
	def test_a_freshly_created_column_reports_everyone_as_missing(self):
		"""`IN (NULL, '', 0)` never matches NULL in SQL.

		The first version of this counter reported 0 employees without a GOSI
		number while all 11 were missing one — a gap report that says "nothing to
		do" is worse than no gap report.
		"""
		active = frappe.db.count("Employee", {"status": "Active"})
		if not active:
			self.skipTest("no active employees")

		with_number = frappe.db.count(
			"Employee", {"status": "Active", "custom_gosi_number": ["is", "set"]}
		)
		self.assertEqual(
			hr_setup._employees_missing("custom_gosi_number"), active - with_number
		)

	def test_a_missing_field_says_so_rather_than_returning_zero(self):
		self.assertEqual(
			hr_setup._employees_missing("custom_field_that_does_not_exist"), "field not created"
		)


class TestSalaryComponentHousekeeping(FrappeTestCase):
	def test_our_own_components_are_never_swept(self):
		"""They are unreferenced BY DESIGN until HR puts them on a structure."""
		summary = hr_setup.unused_salary_components()
		for name in hr_setup.OUR_COMPONENTS:
			with self.subTest(component=name):
				self.assertNotIn(name, summary["unused_and_still_enabled"])
				self.assertFalse(frappe.db.get_value("Salary Component", name, "disabled"))

	def test_every_reference_point_is_checked_not_just_salary_detail(self):
		"""Additional Salary, Retention Bonus, Gratuity and Leave Type all link here.

		Counting only Salary Detail would call a component unused while an
		Additional Salary row still pointed at it.
		"""
		summary = hr_setup.unused_salary_components()
		declared = frappe.db.sql(
			"""SELECT COUNT(*) FROM (
			     SELECT parent, fieldname FROM `tabDocField`
			     WHERE fieldtype = 'Link' AND options = 'Salary Component'
			     UNION
			     SELECT dt, fieldname FROM `tabCustom Field`
			     WHERE fieldtype = 'Link' AND options = 'Salary Component') t"""
		)[0][0]
		self.assertGreater(summary["reference_points_checked"], 1)
		self.assertLessEqual(summary["reference_points_checked"], declared)

	def test_the_report_does_not_disable_anything(self):
		"""It reports. Disabling a component someone is about to use is not cleanup."""
		before = frappe.db.count("Salary Component", {"disabled": 1})
		hr_setup.unused_salary_components()
		self.assertEqual(frappe.db.count("Salary Component", {"disabled": 1}), before)

	def test_a_referenced_component_is_never_listed_as_unused(self):
		used = frappe.db.sql_list(
			"SELECT DISTINCT salary_component FROM `tabSalary Detail` "
			"WHERE salary_component IS NOT NULL"
		)
		if not used:
			self.skipTest("no salary structures on this site")
		summary = hr_setup.unused_salary_components()
		for name in used:
			self.assertNotIn(name, summary["unused_and_still_enabled"])
