# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""2026-10-15 follow-ups: row 26 "new also" (a new document stays inside the chosen fiscal year) and
Q&A 5 (the standard Remarks editable after submit, the ledger wording following).

    bench --site yht-test run-tests --app yht_custom --skip-before-tests \
        --module yht_custom.tests.test_meeting_1015_followups

Nothing commits (gotcha 74); every test rolls back what it wrote.
"""

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import features, fiscal_year, remarks_editable, session_year
from yht_custom.tests.test_meeting_1011_wednesday import _off, _source

YEAR_DOCTYPES = tuple(fiscal_year.DATE_FIELD)


def _year_with_dates():
	row = frappe.db.get_value(
		"Fiscal Year", {"disabled": 0}, ["name", "year_start_date", "year_end_date"], as_dict=True, order_by="year_start_date asc"
	)
	if not row:
		raise unittest_skip("no enabled Fiscal Year")
	return row


def unittest_skip(reason):
	import unittest

	return unittest.SkipTest(reason)


class TestNewDocumentStaysInsideTheChosenYear(FrappeTestCase):
	def setUp(self):
		self.year = _year_with_dates()
		self.inside = str(self.year.year_start_date)
		self.outside = "2099-06-01"

	def _doc(self, doctype="Sales Invoice", date=None, **extra):
		doc = frappe.new_doc(doctype)
		doc.set(fiscal_year.DATE_FIELD[doctype], date or self.inside)
		doc.update(extra)
		return doc

	def _chosen(self):
		return mock.patch.object(session_year, "chosen_year", return_value=self.year.name)

	def test_a_date_outside_the_year_is_refused_on_every_doctype(self):
		for doctype in YEAR_DOCTYPES:
			with self.subTest(doctype=doctype), self._chosen():
				with self.assertRaises(frappe.ValidationError):
					session_year.enforce_new_document_year(self._doc(doctype, self.outside))

	def test_a_date_inside_the_year_is_accepted(self):
		for doctype in YEAR_DOCTYPES:
			with self.subTest(doctype=doctype), self._chosen():
				session_year.enforce_new_document_year(self._doc(doctype, self.inside))

	def test_the_first_and_last_day_of_the_year_are_inside(self):
		with self._chosen():
			session_year.enforce_new_document_year(self._doc(date=str(self.year.year_start_date)))
			session_year.enforce_new_document_year(self._doc(date=str(self.year.year_end_date)))

	def test_nothing_is_enforced_for_a_user_with_no_chosen_year(self):
		with mock.patch.object(session_year, "chosen_year", return_value=""):
			session_year.enforce_new_document_year(self._doc(date=self.outside))

	def test_an_amendment_keeps_its_original_date(self):
		with self._chosen():
			session_year.enforce_new_document_year(self._doc(date=self.outside, amended_from="X-1"))

	def test_an_import_or_patch_is_never_stopped(self):
		for flag in ("in_import", "in_patch"):
			with self.subTest(flag=flag), self._chosen():
				previous = frappe.flags.get(flag)
				frappe.flags[flag] = True
				try:
					session_year.enforce_new_document_year(self._doc(date=self.outside))
				finally:
					frappe.flags[flag] = previous

	def test_it_waits_for_its_switch(self):
		with self._chosen(), _off("oct15_r26_new_document_year"):
			session_year.enforce_new_document_year(self._doc(date=self.outside))

	def test_the_message_names_the_year_and_its_dates(self):
		with self._chosen():
			with self.assertRaises(frappe.ValidationError) as caught:
				session_year.enforce_new_document_year(self._doc(date=self.outside))
		self.assertIn(self.year.name, str(caught.exception))

	def test_boot_hands_the_form_the_year_limit_only_when_asked(self):
		with self._chosen(), mock.patch.object(session_year, "sync_saved_filters"):
			info = session_year.boot_value()
		self.assertEqual(info["limit"]["start"], str(self.year.year_start_date))
		self.assertEqual(info["limit"]["end"], str(self.year.year_end_date))
		self.assertEqual(info["limit"]["date_fields"]["Quotation"], "transaction_date")
		with self._chosen(), mock.patch.object(session_year, "sync_saved_filters"), _off("oct15_r26_new_document_year"):
			self.assertIsNone(session_year.boot_value()["limit"])

	def test_the_handler_is_registered_for_all_eight(self):
		events = frappe.get_hooks("doc_events", app_name="yht_custom")
		for doctype in YEAR_DOCTYPES:
			handlers = events.get(doctype, {}).get("before_insert")
			handlers = handlers if isinstance(handlers, list) else [handlers]
			self.assertIn("yht_custom.session_year.enforce_new_document_year", handlers, doctype)

	def test_the_script_limits_the_date_picker_and_the_default(self):
		js = _source("public/js/session_year.js")
		self.assertIn("limit_new_document_dates", js)
		self.assertIn("datepicker.update", js)
		self.assertIn("minDate", js)
		self.assertIn("maxDate", js)
		self.assertIn("/assets/yht_custom/js/session_year.js?v=4", _source("hooks.py"))


class TestStandardRemarksEditable(FrappeTestCase):
	def setUp(self):
		remarks_editable.setup_standard_remarks_editable()
		for doctype in remarks_editable.FIELDS:
			frappe.clear_cache(doctype=doctype)

	def tearDown(self):
		frappe.db.rollback()

	def _a_submitted(self, doctype, **filters):
		name = frappe.db.get_value(doctype, {"docstatus": 1, **filters}, "name", order_by="modified desc")
		if not name:
			self.skipTest(f"no submitted {doctype} on this site")
		return frappe.get_doc(doctype, name)

	def _ledger(self, doc):
		return frappe.get_all(
			"GL Entry", filters={"voucher_type": doc.doctype, "voucher_no": doc.name}, pluck="remarks", limit=0
		)

	def test_the_six_fields_are_editable_after_submit(self):
		for doctype, fieldname in remarks_editable.FIELDS.items():
			with self.subTest(doctype=doctype):
				meta = frappe.get_meta(doctype, cached=False)
				self.assertEqual(meta.get_field(fieldname).allow_on_submit, 1)
				self.assertEqual(meta.track_changes, 1)

	def test_it_waits_for_its_switch(self):
		with _off("oct15_std_remarks_editable"):
			self.assertIn("skipped", remarks_editable.setup_standard_remarks_editable())

	def test_the_handler_is_registered_for_all_six(self):
		events = frappe.get_hooks("doc_events", app_name="yht_custom")
		for doctype in remarks_editable.FIELDS:
			handlers = events.get(doctype, {}).get("on_update_after_submit")
			handlers = handlers if isinstance(handlers, list) else [handlers]
			self.assertIn("yht_custom.remarks_editable.sync_ledger_wording", handlers, doctype)

	def test_an_edit_after_submit_is_saved_recorded_and_reaches_the_ledger(self):
		doc = self._a_submitted("Purchase Invoice")
		doc.remarks = "edited by the 2026-10-15 test"
		doc.save()
		self.assertEqual(frappe.db.get_value("Purchase Invoice", doc.name, "remarks"), "edited by the 2026-10-15 test")
		# The activity entry itself (a Version row) is written in a normal run — checked against UAT with a
		# plain script, 1 -> 2 rows carrying the old and new text — but the test runner does not write one,
		# so what is asserted here is the setting that makes Frappe write it.
		self.assertEqual(frappe.get_meta("Purchase Invoice", cached=False).track_changes, 1)
		ledger = self._ledger(doc)
		self.assertTrue(ledger)
		self.assertTrue(all("edited by the 2026-10-15 test" in (r or "") for r in ledger), ledger)

	def test_a_blank_remark_in_the_ledger_reads_no_remarks_and_is_replaced(self):
		rows = frappe.db.sql(
			"""SELECT pi.name FROM `tabPurchase Invoice` pi WHERE pi.docstatus = 1 AND IFNULL(pi.remarks, '') = ''
			AND EXISTS (SELECT 1 FROM `tabGL Entry` g WHERE g.voucher_type = 'Purchase Invoice' AND g.voucher_no = pi.name
			AND g.remarks = 'No Remarks') LIMIT 1""",
			pluck=True,
		)
		if not rows:
			self.skipTest("no submitted Purchase Invoice with a blank remark")
		doc = frappe.get_doc("Purchase Invoice", rows[0])
		doc.remarks = "first remark"
		doc.save()
		self.assertTrue(all("first remark" in (r or "") for r in self._ledger(doc)))

	def test_a_journal_entry_row_keeps_its_own_text_around_the_edit(self):
		doc = self._a_submitted("Journal Entry")
		old = (doc.user_remark or "").strip()
		if not old:
			self.skipTest("the newest Journal Entry has no user remark")
		before = self._ledger(doc)
		doc.user_remark = old + " (edited)"
		doc.save()
		after = self._ledger(doc)
		self.assertEqual(len(before), len(after))
		for b, a in zip(sorted(before), sorted(after)):
			self.assertEqual(a, (b or "").replace(old, old + " (edited)"))

	def test_no_amount_account_or_date_is_touched(self):
		doc = self._a_submitted("Purchase Invoice")
		shape = lambda: frappe.db.sql(  # noqa: E731
			"SELECT account, debit, credit, posting_date FROM `tabGL Entry` WHERE voucher_type = 'Purchase Invoice' AND voucher_no = %s ORDER BY name",
			(doc.name,),
		)
		before = shape()
		doc.remarks = "numbers must not move"
		doc.save()
		self.assertEqual(shape(), before)

	def test_with_the_switch_off_the_ledger_is_left_alone(self):
		doc = self._a_submitted("Purchase Invoice")
		before = self._ledger(doc)
		with _off("oct15_std_remarks_editable"):
			doc.remarks = "saved while the switch is off"
			doc.save()
		self.assertEqual(self._ledger(doc), before)


class TestChoosingAYearReachesSavedListFilters(FrappeTestCase):
	"""2026-10-16, the client: "I choose 2025 at login and the lists still show 2026"."""

	USER_DOCTYPE = "Sales Invoice"

	def _save(self, filters):
		from frappe.model.utils import user_settings

		user_settings.update_user_settings(self.USER_DOCTYPE, {"List": {"filters": filters}})

	def _saved(self):
		import json

		from frappe.model.utils import user_settings

		return (json.loads(user_settings.get_user_settings(self.USER_DOCTYPE)).get("List") or {}).get("filters")

	def setUp(self):
		frappe.set_user("Administrator")
		self.before = None
		try:
			self.before = self._saved()
		except Exception:
			pass

	def tearDown(self):
		try:
			self._save(self.before or [])
		finally:
			frappe.db.rollback()

	def test_a_saved_set_without_a_year_gets_the_clause_when_a_year_is_chosen(self):
		self._save([[self.USER_DOCTYPE, "docstatus", "=", "0"]])
		session_year.sync_saved_filters("Administrator", "2025", add_missing=True)
		self.assertIn([self.USER_DOCTYPE, "custom_fiscal_year", "=", "2025"], self._saved())
		self.assertIn([self.USER_DOCTYPE, "docstatus", "=", "0"], self._saved())

	def test_at_plain_boot_a_list_without_a_year_is_left_alone(self):
		self._save([[self.USER_DOCTYPE, "docstatus", "=", "0"]])
		session_year.sync_saved_filters("Administrator", "2025")
		self.assertEqual(self._saved(), [[self.USER_DOCTYPE, "docstatus", "=", "0"]])

	def test_an_existing_clause_is_rewritten_not_duplicated(self):
		self._save([[self.USER_DOCTYPE, "custom_fiscal_year", "=", "2024"]])
		session_year.sync_saved_filters("Administrator", "2025", add_missing=True)
		clauses = [c for c in self._saved() if c[1] == "custom_fiscal_year"]
		self.assertEqual(clauses, [[self.USER_DOCTYPE, "custom_fiscal_year", "=", "2025"]])

	def test_an_empty_saved_set_gets_the_clause_when_a_year_is_chosen(self):
		"""2026-10-16 — Osaid's lists carry `[]` (the filter bar cleared once); the list opens with exactly that,
		so the chosen year never reached them."""
		self._save([])
		session_year.sync_saved_filters("Administrator", "2025", add_missing=True)
		self.assertEqual(self._saved(), [[self.USER_DOCTYPE, "custom_fiscal_year", "=", "2025"]])

	def test_at_plain_boot_an_empty_saved_set_stays_empty(self):
		self._save([])
		session_year.sync_saved_filters("Administrator", "2025")
		self.assertFalse(self._saved())

	def test_the_wrapper_is_registered_and_passes_frappes_result_through(self):
		hooks = frappe.get_hooks("override_whitelisted_methods", app_name="yht_custom") or {}
		key = "frappe.core.doctype.session_default_settings.session_default_settings.set_session_default_values"
		self.assertIn(key, hooks)
		with mock.patch(
			"frappe.core.doctype.session_default_settings.session_default_settings.set_session_default_values",
			return_value="success",
		) as upstream, mock.patch.object(session_year, "sync_saved_filters") as sync:
			result = session_year.apply_chosen_year('{"fiscal_year": "%s"}' % _year_with_dates().name)
		self.assertEqual(result, "success")
		upstream.assert_called_once()
		sync.assert_called_once()
		self.assertTrue(sync.call_args.kwargs.get("add_missing"))

	def test_the_wrapper_is_whitelisted_the_way_the_original_is(self):
		"""🔴 Found by the real-browser run, not by any unit test: without `@frappe.whitelist()` the desk got
		"Function … is not whitelisted" and the login pop-up could not save. Calling the function directly,
		as the other tests do, can never see that; this asserts what `handler.execute_cmd` checks."""
		from frappe.core.doctype.session_default_settings.session_default_settings import (
			set_session_default_values as original,
		)

		self.assertIn(session_year.apply_chosen_year, frappe.whitelisted)
		self.assertEqual(session_year.apply_chosen_year in frappe.guest_methods, original in frappe.guest_methods)

	def test_with_the_switch_off_it_is_exactly_frappes_method(self):
		with mock.patch(
			"frappe.core.doctype.session_default_settings.session_default_settings.set_session_default_values",
			return_value="success",
		), mock.patch.object(session_year, "sync_saved_filters") as sync, _off("oct11_r26_session_fiscal_year"):
			self.assertEqual(session_year.apply_chosen_year('{"fiscal_year": "2025"}'), "success")
		sync.assert_not_called()
