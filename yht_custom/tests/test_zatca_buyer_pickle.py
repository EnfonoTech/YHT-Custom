# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Row 28's class override must survive being queued (found live, 2026-10-14).

`ksa_compliance` queues `_submit_additional_fields(doc=<Sales Invoice Additional Fields>)` after every
Sales Invoice submit and rq pickles the argument. The first version of the override built its class
inside a function, so the pickle failed with "Can't pickle local object" and every submit answered 500.
The row-28 unit tests called the methods directly and never pickled anything.

    bench --site yht-test run-tests --app yht_custom --skip-before-tests \
        --module yht_custom.tests.test_zatca_buyer_pickle
"""

import pickle

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom import zatca_buyer


class TestTheOverrideClassCanBeQueued(FrappeTestCase):
	def setUp(self):
		if zatca_buyer.YHTSalesInvoiceAdditionalFields is None:
			self.skipTest("ksa_compliance is not installed")

	def test_the_class_has_a_module_level_name(self):
		cls = zatca_buyer.YHTSalesInvoiceAdditionalFields
		self.assertEqual(cls.__qualname__, "YHTSalesInvoiceAdditionalFields")
		self.assertNotIn("<locals>", cls.__qualname__)

	def test_the_class_pickles_by_reference_and_comes_back_as_itself(self):
		cls = zatca_buyer.YHTSalesInvoiceAdditionalFields
		self.assertIs(pickle.loads(pickle.dumps(cls)), cls)

	def test_a_document_of_the_class_pickles_the_way_rq_does_it(self):
		"""What `enqueue(..., doc=siaf)` does with its argument."""
		doc = frappe.new_doc("Sales Invoice Additional Fields")
		self.assertIsInstance(doc, zatca_buyer.YHTSalesInvoiceAdditionalFields)
		restored = pickle.loads(pickle.dumps(doc))
		self.assertIsInstance(restored, zatca_buyer.YHTSalesInvoiceAdditionalFields)

	def test_the_hook_still_points_at_the_same_class(self):
		hooked = (frappe.get_hooks("override_doctype_class", app_name="yht_custom") or {}).get(
			"Sales Invoice Additional Fields"
		)
		target = hooked[-1] if isinstance(hooked, list) else hooked
		self.assertIs(frappe.get_attr(target), zatca_buyer.YHTSalesInvoiceAdditionalFields)
