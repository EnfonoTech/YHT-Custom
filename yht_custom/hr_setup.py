# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""HR module configuration on hrms (plan 6.8).

MEASURED FIRST. HR here is not greenfield — it is live and half-configured:

    13 Employees (11 active)      191 Salary Slips     32 Payroll Entries
    13 Salary Structures          797 Attendance rows  6 Leave Types
    62 Salary Components, of which 50 are referenced by nothing at all
    and 34 are named for OTHER group entities (WAETC, AAATCJ, -KJ, AJ, YHTCY)

Four things were missing outright, and each one breaks something concrete:

1. NO GOSI COMPONENT OF ANY KIND. Social insurance is not optional in Saudi
   Arabia and there was no deduction for it anywhere in the system.
2. The only Payroll Period ends 2025-12-31. A 2026 Payroll Entry has no period.
3. The company's default Holiday List is `Standard Holiday 2025`, also expired.
   The only 2026 list is `Weekly Off` with zero holidays in it.
4. 0 Leave Allocations, so no Leave Application can validate against a balance,
   and the Leave Types themselves do not match Saudi Labour Law.

WHAT THIS MODULE WILL NOT DO. It never edits an existing Salary Structure, never
touches a Salary Slip, and never deletes a Salary Component — 191 slips reference
those components and 13 structures are submitted. It creates what is missing and
reports what needs a human. `hr_gaps()` prints the current picture.

THE GOSI WAGE BASE IS A CLIENT DECISION, AND IT IS NOT GUESSED HERE.
By law the contribution base is basic salary plus housing allowance, capped. This
client's components cannot be mapped to that automatically: there are nine
different components with "BASIC SALARY" in the name, most belonging to other
group entities, and the housing allowance appears as `ACCOMODATION - KJ` and
`BACHELOR ACCOMODATIO WAETC`. So `GOSI Wage` is created as a STATISTICAL
component with a formula of `base`, and HR must repoint that one formula at the
right components. Getting it wrong under-withholds statutory contributions, which
is not a decision an installer should make silently.
"""

import frappe
from frappe.utils import getdate

#: GOSI, standard scheme. Employee 9.75% = 9% pension + 0.75% SANED.
#: Employer 11.75% = 9% pension + 0.75% SANED + 2% occupational hazards.
#: Non-Saudis: employer pays 2% occupational hazards only, employee pays nothing.
#:
#: ⚠️ The 2024 reform raises the PENSION share for employees who joined on or
#: after 3 July 2024, stepping up from 9% annually. It is per-employee and
#: date-dependent, so it is deliberately NOT modelled here — confirm each new
#: joiner's rate with the client's GOSI portal before running payroll for them.
GOSI_EMPLOYEE_RATE = 9.75
GOSI_EMPLOYER_RATE = 11.75
GOSI_NON_SAUDI_EMPLOYER_RATE = 2.0
#: Monthly contribution ceiling, SAR.
GOSI_WAGE_CAP = 45000

EMPLOYEE_CUSTOM_FIELDS = [
	{
		"fieldname": "custom_is_saudi_national",
		"label": "Saudi National",
		"fieldtype": "Check",
		"insert_after": "passport_number",
		"description": "Drives the GOSI rate. Saudi nationals contribute; non-Saudis carry occupational-hazard cover only.",
	},
	{
		"fieldname": "custom_gosi_number",
		"label": "GOSI Number",
		"fieldtype": "Data",
		"insert_after": "custom_is_saudi_national",
	},
	{
		"fieldname": "custom_iqama_number",
		"label": "Iqama Number",
		"fieldtype": "Data",
		"insert_after": "custom_gosi_number",
		"depends_on": "eval:!doc.custom_is_saudi_national",
	},
]

#: Saudi Labour Law leave entitlements. `max_leaves_allowed` is the annual cap.
#: Article numbers are in the description so an HR user can check the source.
LEAVE_TYPES = [
	{
		"leave_type_name": "Annual Leave",
		"max_leaves_allowed": 21,
		"is_carry_forward": 1,
		"include_holiday": 0,
		"description": "Art. 109 — 21 days, rising to 30 after five years' service. Raise the cap per employee on the Leave Policy.",
	},
	{
		"leave_type_name": "Sick Leave Full Pay",
		"max_leaves_allowed": 30,
		"description": "Art. 117 — first 30 days at full pay.",
	},
	{
		"leave_type_name": "Sick Leave 75 Percent",
		"max_leaves_allowed": 60,
		"description": "Art. 117 — days 31 to 90 at 75% of wage. Pay the 25% shortfall as a deduction.",
	},
	{
		"leave_type_name": "Sick Leave Unpaid",
		"max_leaves_allowed": 30,
		"is_lwp": 1,
		"description": "Art. 117 — days 91 to 120, unpaid.",
	},
	{
		"leave_type_name": "Hajj Leave",
		"max_leaves_allowed": 15,
		"description": "Art. 114 — 10 to 15 days, once in a period of service, for an employee who has not performed Hajj before.",
	},
	{
		"leave_type_name": "Maternity Leave",
		"max_leaves_allowed": 70,
		"description": "Art. 151 — 10 weeks, distributed as the employee chooses from four weeks before the expected delivery date.",
	},
	{
		"leave_type_name": "Marriage Leave",
		"max_leaves_allowed": 5,
		"description": "Art. 113 — 5 days.",
	},
	{
		"leave_type_name": "Bereavement Leave",
		"max_leaves_allowed": 5,
		"description": "Art. 113 — 5 days on the death of a spouse, parent or child.",
	},
	{
		"leave_type_name": "Newborn Leave",
		"max_leaves_allowed": 3,
		"description": "Art. 113 — 3 days on the birth of a child.",
	},
]

#: Saudi public holidays with FIXED Gregorian dates. Eid Al Fitr and Eid Al Adha
#: are lunar and move every year, so they are NOT invented here — `hr_gaps`
#: reports their absence instead.
FIXED_HOLIDAYS = (
	((2, 22), "Founding Day"),
	((9, 23), "National Day"),
)

#: Saudi working week: Sunday to Thursday.
WEEKLY_OFF_DAYS = ("Friday", "Saturday")


# ------------------------------------------------------------------- entry point


def setup_hr(year: int | None = None) -> dict:
	"""Create every missing piece. Never edits what is already there."""
	if not frappe.db.exists("DocType", "Salary Component"):
		return {"skipped": "hrms is not installed"}

	year = year or getdate().year
	return {
		"employee_fields": _employee_fields(),
		"salary_components": _gosi_components(),
		"leave_types": _leave_types(),
		"holiday_list": _holiday_list(year),
		"payroll_period": _payroll_period(year),
	}


def _employee_fields() -> dict:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	missing = [
		field
		for field in EMPLOYEE_CUSTOM_FIELDS
		if not frappe.get_meta("Employee").get_field(field["fieldname"])
	]
	if missing:
		create_custom_fields({"Employee": missing}, ignore_validate=True)
	return {"created": len(missing)}


# ---------------------------------------------------------------------- GOSI


def _gosi_components() -> dict:
	"""Three components: the wage base, the employee share, the employer share.

	The employer share is `statistical_component`, so it shows on the slip for
	reporting and filing without touching net pay — an employer contribution is a
	company cost, not something withheld from the employee.
	"""
	created = []

	specs = [
		{
			"salary_component": "GOSI Wage",
			"salary_component_abbr": "GOSIW",
			"type": "Earning",
			"statistical_component": 1,
			"amount_based_on_formula": 1,
			# `base` is a PLACEHOLDER. See the module docstring: the legal base is
			# basic + housing, and this client's component naming cannot be mapped
			# to that automatically.
			"formula": f"min(base, {GOSI_WAGE_CAP})",
			"description": (
				"⚠️ CONFIGURE ME. The GOSI contribution base is basic salary plus housing "
				f"allowance, capped at SAR {GOSI_WAGE_CAP:,}. This ships as `base` because this "
				"site carries nine components with 'BASIC SALARY' in the name and two different "
				"accommodation components. Repoint this formula at the correct component "
				"abbreviations before running payroll."
			),
		},
		{
			"salary_component": "GOSI Employee",
			"salary_component_abbr": "GOSIE",
			"type": "Deduction",
			"amount_based_on_formula": 1,
			"formula": f"GOSIW * {GOSI_EMPLOYEE_RATE} / 100",
			"condition": "custom_is_saudi_national",
			"description": (
				f"Art. 4 GOSI — {GOSI_EMPLOYEE_RATE}% of the contribution wage (9% pension + "
				"0.75% SANED). Saudi nationals only; the condition reads "
				"Employee.custom_is_saudi_national. Employees who joined on or after "
				"3 July 2024 step up under the 2024 reform — confirm per employee."
			),
		},
		{
			"salary_component": "GOSI Employer",
			"salary_component_abbr": "GOSIC",
			"type": "Deduction",
			"statistical_component": 1,
			"amount_based_on_formula": 1,
			"formula": (
				f"GOSIW * ({GOSI_EMPLOYER_RATE} if custom_is_saudi_national "
				f"else {GOSI_NON_SAUDI_EMPLOYER_RATE}) / 100"
			),
			"description": (
				f"Company cost, NOT withheld from the employee — hence statistical. "
				f"{GOSI_EMPLOYER_RATE}% for a Saudi national, "
				f"{GOSI_NON_SAUDI_EMPLOYER_RATE}% occupational hazards for everyone else."
			),
		},
	]

	for spec in specs:
		name = spec["salary_component"]
		if frappe.db.exists("Salary Component", name):
			continue
		doc = frappe.new_doc("Salary Component")
		doc.update(spec)
		doc.flags.ignore_permissions = True
		doc.insert()
		created.append(name)

	return {"created": created}


# ------------------------------------------------------------------ leave types


def _leave_types() -> dict:
	created = []
	for spec in LEAVE_TYPES:
		name = spec["leave_type_name"]
		if frappe.db.exists("Leave Type", name):
			continue
		doc = frappe.new_doc("Leave Type")
		doc.update(spec)
		doc.flags.ignore_permissions = True
		doc.insert()
		created.append(name)
	return {"created": created}


# ----------------------------------------------------------------- holiday list


def holiday_list_name(year: int) -> str:
	return f"KATC Holidays {year}"


def _holiday_list(year: int) -> dict:
	"""Weekly offs plus the fixed-date national holidays.

	Eid Al Fitr and Eid Al Adha are lunar. They are NOT guessed — a wrong Eid in a
	holiday list silently changes payment days on every salary slip in that month.
	"""
	name = holiday_list_name(year)
	if frappe.db.exists("Holiday List", name):
		return {"existing": name}

	doc = frappe.new_doc("Holiday List")
	doc.holiday_list_name = name
	doc.from_date = f"{year}-01-01"
	doc.to_date = f"{year}-12-31"
	doc.weekly_off = WEEKLY_OFF_DAYS[0]
	doc.flags.ignore_permissions = True
	doc.insert()

	for day in WEEKLY_OFF_DAYS:
		doc.weekly_off = day
		doc.get_weekly_off_dates()

	for (month, day), description in FIXED_HOLIDAYS:
		date = f"{year}-{month:02d}-{day:02d}"
		if not any(str(row.holiday_date) == date for row in doc.holidays):
			doc.append("holidays", {"holiday_date": date, "description": description})

	doc.save()
	return {"created": name, "holidays": len(doc.holidays)}


# --------------------------------------------------------------- payroll period


def _payroll_period(year: int) -> dict:
	company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	if not company:
		return {"skipped": "no company"}

	start, end = f"{year}-01-01", f"{year}-12-31"
	existing = frappe.db.exists(
		"Payroll Period", {"company": company, "start_date": start, "end_date": end}
	)
	if existing:
		return {"existing": existing}

	doc = frappe.new_doc("Payroll Period")
	doc.company = company
	doc.start_date = start
	doc.end_date = end
	# Payroll Period autonames by PROMPT, so `name` must be set by hand. Without it
	# the insert raises "Please set the document name" — and because an
	# after_migrate step runs in one transaction, that failure rolled back the GOSI
	# components and the Leave Types created earlier in the same step.
	doc.name = f"{frappe.db.get_value('Company', company, 'abbr') or 'Payroll'} {year}"
	doc.flags.ignore_permissions = True
	doc.insert()
	return {"created": doc.name}


# ------------------------------------------------------------------- reporting


def hr_gaps() -> dict:
	"""What still needs a human. Run before the client's first payroll run.

	    bench --site … execute yht_custom.hr_setup.hr_gaps
	"""
	year = getdate().year
	company = frappe.defaults.get_global_default("company")

	structures = frappe.get_all("Salary Structure", filters={"docstatus": 1}, pluck="name")
	with_gosi = set(
		frappe.get_all(
			"Salary Detail",
			filters={"parenttype": "Salary Structure", "salary_component": "GOSI Employee"},
			pluck="parent",
		)
	)

	unused = frappe.db.sql(
		"""SELECT COUNT(*) FROM `tabSalary Component` sc
		   WHERE NOT EXISTS (SELECT 1 FROM `tabSalary Detail` sd
		                     WHERE sd.salary_component = sc.name)"""
	)[0][0]

	summary = {
		"employees_active": frappe.db.count("Employee", {"status": "Active"}),
		"employees_without_nationality": _employees_missing("custom_is_saudi_national"),
		"employees_without_gosi_number": _employees_missing("custom_gosi_number"),
		"structures_submitted": len(structures),
		"structures_without_gosi": sorted(set(structures) - with_gosi),
		"gosi_wage_formula": frappe.db.get_value("Salary Component", "GOSI Wage", "formula"),
		"gosi_wage_still_placeholder": frappe.db.get_value("Salary Component", "GOSI Wage", "formula")
		== f"min(base, {GOSI_WAGE_CAP})",
		"holiday_list_for_this_year": frappe.db.exists("Holiday List", holiday_list_name(year)),
		"company_default_holiday_list": frappe.db.get_value(
			"Company", company, "default_holiday_list"
		)
		if company
		else None,
		"eid_holidays_present": _eid_present(year),
		"payroll_period_for_this_year": bool(
			frappe.db.exists("Payroll Period", {"start_date": f"{year}-01-01"})
		),
		"leave_allocations": frappe.db.count("Leave Allocation"),
		"salary_components_unused": unused,
	}
	print(frappe.as_json(summary, indent=1))
	return summary


def _employees_missing(fieldname: str) -> int | str:
	"""Count actives with nothing in this field.

	`["in", [None, "", 0]]` does NOT work: SQL `IN (NULL, '', 0)` never matches a
	NULL, so a freshly created column reported 0 employees missing when all 11
	were. `["is", "not set"]` is the filter that covers NULL and empty.
	"""
	if not frappe.get_meta("Employee").get_field(fieldname):
		return "field not created"

	field = frappe.get_meta("Employee").get_field(fieldname)
	if field.fieldtype == "Check":
		return frappe.db.count("Employee", {"status": "Active", fieldname: 0})
	return frappe.db.count("Employee", {"status": "Active", fieldname: ["is", "not set"]})


def _eid_present(year: int) -> bool:
	"""Eid is lunar and must be entered by hand every year."""
	name = holiday_list_name(year)
	if not frappe.db.exists("Holiday List", name):
		return False
	descriptions = frappe.get_all(
		"Holiday", filters={"parent": name}, pluck="description"
	)
	return any("eid" in (text or "").lower() for text in descriptions)
