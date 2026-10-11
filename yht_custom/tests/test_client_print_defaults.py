# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Osaid Kamal, 2026-10-11: "please make sure the print formats are the following
in the live version: SALES-INVOICE, SALES-QUOTATION, PURCHASE-ORDER, DELIVERY-NOTE
W/O HEAD."

Those are the client's own site-built formats, made default by Property Setters on
the live site. The risk was never setting them — it was `backfill_meeting_0923_data`,
a patch that had not yet run on live, calling a cleanup that deleted EVERY
`default_print_format` setter on five doctypes. These tests hold the cleanup to
deleting only what is stale.

Nothing here commits (gotcha 74); `FrappeTestCase` rolls the fixtures back per class.
"""

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import print_consolidation as pc

PROP = "default_print_format"
PERSON = "someone@example.com"


def _format(name, doctype):
	"""A client-built format (`standard = No`), created only if this site lacks it."""
	if not frappe.db.exists("Print Format", name):
		frappe.get_doc(
			{
				"doctype": "Print Format",
				"name": name,
				"doc_type": doctype,
				"print_format_type": "Jinja",
				"custom_format": 1,
				"standard": "No",
				"html": "<p>test</p>",
			}
		).insert(ignore_permissions=True)
	return name


def _one_of_ours():
	"""An enabled format this app ships."""
	names = frappe.get_all(
		"Print Format", filters={"standard": "Yes", "disabled": 0, "module": "Yht Custom"}, pluck="name", limit=1
	)
	if not names:
		raise unittest_skip("no enabled Yht Custom print format on this site")
	return names[0]


def unittest_skip(reason):
	import unittest

	return unittest.SkipTest(reason)


def _clear(doctype):
	for name in frappe.get_all("Property Setter", filters={"doc_type": doctype, "property": PROP}, pluck="name"):
		frappe.delete_doc("Property Setter", name, force=1, ignore_permissions=True)


def _setter(doctype, value, modified_by):
	"""A default_print_format setter as saved by `modified_by`."""
	_clear(doctype)
	doc = frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": "DocType",
			"doc_type": doctype,
			"property": PROP,
			"value": value,
			"property_type": "Data",
		}
	).insert(ignore_permissions=True)
	frappe.db.set_value("Property Setter", doc.name, "modified_by", modified_by, update_modified=False)
	return doc.name


def _plan_for(name):
	"""(where, why) for one setter in the real cleanup's plan."""
	plan = pc.classify_default_print_format_setters()
	for where in ("delete", "keep"):
		for setter, _doctype, _value, why in plan[where]:
			if setter == name:
				return where, why
	return None, None


class TestTheCleanupSparesTheClientsChoices(FrappeTestCase):
	def test_a_client_built_format_is_kept_whoever_saved_the_setter(self):
		"""Includes a setter a script saved on the client's behalf (modified_by
		Administrator) — which is how the live defaults were set on 2026-10-11."""
		fmt = _format("_T-CD-CLIENT", "Sales Invoice")
		for saved_by in (PERSON, "Administrator"):
			with self.subTest(saved_by=saved_by):
				self.assertEqual(_plan_for(_setter("Sales Invoice", fmt, saved_by))[0], "keep")

	def test_a_named_users_pick_of_one_of_our_formats_is_kept_while_it_is_enabled(self):
		"""yaser@ pinned Sales Order to KATC Proforma Invoice on 2026-09-24."""
		name = _setter("Sales Order", _one_of_ours(), PERSON)
		self.assertEqual(_plan_for(name)[0], "keep")

	def test_provisioning_pinning_one_of_our_formats_is_deleted(self):
		"""The original incident: Sales Invoice pinned to KATC Tax Invoice by this
		module's own earlier code, overriding the DocType row."""
		name = _setter("Sales Invoice", _one_of_ours(), "Administrator")
		where, why = _plan_for(name)
		self.assertEqual(where, "delete")
		self.assertIn("provisioning", why)

	def test_a_default_that_points_nowhere_or_at_a_disabled_format_is_deleted(self):
		missing = _setter("Quotation", "_T-CD-NO-SUCH-FORMAT", PERSON)
		self.assertEqual(_plan_for(missing), ("delete", "points at a Print Format that does not exist"))

		off = _format("_T-CD-OFF", "Delivery Note")
		frappe.db.set_value("Print Format", off, "disabled", 1, update_modified=False)
		disabled = _setter("Delivery Note", off, PERSON)
		self.assertEqual(_plan_for(disabled), ("delete", "points at a disabled Print Format"))

	def test_a_blank_default_is_kept_when_a_person_cleared_it(self):
		self.assertEqual(_plan_for(_setter("Purchase Order", "", PERSON))[0], "keep")
		self.assertEqual(_plan_for(_setter("Purchase Order", "", "Administrator"))[0], "delete")

	def test_the_drop_deletes_what_it_classified_and_nothing_else(self):
		"""`_delete_setters` is what both the patch and the consolidation call."""
		keep = _setter("Sales Invoice", _format("_T-CD-KEEP", "Sales Invoice"), PERSON)
		gone = _setter("Quotation", "_T-CD-NO-SUCH-FORMAT", PERSON)
		plan = pc.classify_default_print_format_setters()
		pc._delete_setters([e for e in plan["delete"] if e[0] == gone])
		self.assertTrue(frappe.db.exists("Property Setter", keep))
		self.assertFalse(frappe.db.exists("Property Setter", gone))


class TestCheckClientDefaults(FrappeTestCase):
	def test_ok_fail_and_skip_are_three_different_answers(self):
		good = _format("_T-CD-GOOD", "Quotation")
		_setter("Quotation", good, PERSON)
		bad = _format("_T-CD-BAD", "Delivery Note")
		_clear("Delivery Note")  # no setter: the effective default is the DocType row, not `bad`
		expected = {"Sales Invoice": "_T-CD-ABSENT", "Quotation": good, "Delivery Note": bad}
		with mock.patch.object(pc, "CLIENT_DEFAULT_PRINT_FORMATS", expected):
			rows = pc.check_client_defaults()
		self.assertTrue(rows["Sales Invoice"]["status"].startswith("SKIP"))
		self.assertEqual(rows["Quotation"]["status"], "OK")
		self.assertEqual(rows["Delivery Note"]["status"], "FAIL")

	def test_the_clients_four_are_declared(self):
		self.assertEqual(
			pc.CLIENT_DEFAULT_PRINT_FORMATS,
			{
				"Sales Invoice": "SALES-INVOICE",
				"Quotation": "SALES-QUOTATION",
				"Purchase Order": "PURCHASE-ORDER",
				"Delivery Note": "DELIVERY-NOTE W/O HEAD",
			},
		)
		self.assertTrue(set(pc.CLIENT_DEFAULT_PRINT_FORMATS) <= set(pc.DOCTYPES))


class TestTheConsolidationDropsOnlyWhatItJustMadeStale(FrappeTestCase):
	def test_retiring_the_format_a_person_chose_drops_that_default(self):
		"""The live Sales Order default is `KATC Proforma Invoice`, which CR-004 retires."""
		if not frappe.db.exists("Print Format", "KATC Proforma Invoice"):
			self.skipTest("KATC Proforma Invoice is not on this site")
		name = _setter("Sales Order", "KATC Proforma Invoice", "yaser@example.com")
		self.assertEqual(_plan_for(name)[0], "keep" if not frappe.db.get_value("Print Format", "KATC Proforma Invoice", "disabled") else "delete")
		with mock.patch.object(pc.features, "enabled", return_value=True):
			result = pc.setup_print_consolidation()
		self.assertIn("stale_defaults_dropped", result)
		self.assertFalse(frappe.db.exists("Property Setter", name), "the default still points at a disabled format")
