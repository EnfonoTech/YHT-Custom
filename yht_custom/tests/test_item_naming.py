# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Tests for item-group-wise item code generation."""

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom.item_naming import generate_code, get_group_prefix, peek_next_code

GROUP_WITH_PREFIX = "_Test YHT Prefixed Group"
GROUP_NO_PREFIX = "_Test YHT Plain Group"
PREFIX = "ZZT"


class TestItemNaming(FrappeTestCase):
	def setUp(self):
		for name, prefix in ((GROUP_WITH_PREFIX, PREFIX), (GROUP_NO_PREFIX, None)):
			if not frappe.db.exists("Item Group", name):
				doc = frappe.get_doc(
					{
						"doctype": "Item Group",
						"item_group_name": name,
						"parent_item_group": "All Item Groups",
						"is_group": 0,
					}
				)
				if prefix:
					doc.custom_item_code_prefix = prefix
				doc.insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	def _new_item(self, item_group, item_code=None):
		doc = frappe.new_doc("Item")
		doc.item_name = "_Test YHT Item"
		doc.item_group = item_group
		doc.stock_uom = frappe.db.get_value("UOM", {}, "name") or "Nos"
		doc.is_stock_item = 0
		if item_code:
			doc.item_code = item_code
		doc.insert(ignore_permissions=True)
		return doc

	def test_prefix_is_read_from_the_group(self):
		self.assertEqual(get_group_prefix(GROUP_WITH_PREFIX), PREFIX)
		self.assertEqual(get_group_prefix(GROUP_NO_PREFIX), "")
		self.assertEqual(get_group_prefix(None), "")

	def test_code_is_generated_when_item_code_is_blank(self):
		doc = self._new_item(GROUP_WITH_PREFIX)
		self.assertTrue(doc.item_code.startswith(f"{PREFIX}-"), doc.item_code)
		# autoname ends with name = item_code, so they must agree
		self.assertEqual(doc.name, doc.item_code)

	def test_a_typed_code_is_never_overwritten(self):
		"""A code the user entered on purpose must survive."""
		doc = self._new_item(GROUP_WITH_PREFIX, item_code="_TEST-KEEP-ME")
		self.assertEqual(doc.item_code, "_TEST-KEEP-ME")

	def test_group_without_prefix_keeps_manual_codes(self):
		"""Groups with no prefix must behave exactly as before — no breakage."""
		doc = self._new_item(GROUP_NO_PREFIX, item_code="_TEST-MANUAL-1")
		self.assertEqual(doc.item_code, "_TEST-MANUAL-1")

	def test_codes_increment(self):
		first = self._new_item(GROUP_WITH_PREFIX).item_code
		second = self._new_item(GROUP_WITH_PREFIX).item_code
		self.assertNotEqual(first, second)
		self.assertLess(first, second)

	def test_peek_does_not_consume_the_counter(self):
		"""A preview that burned a number would leave a gap per abandoned form."""
		peek_one = peek_next_code(GROUP_WITH_PREFIX)
		peek_two = peek_next_code(GROUP_WITH_PREFIX)
		self.assertEqual(peek_one, peek_two)
		# and the next real generation matches what was previewed
		self.assertEqual(generate_code(GROUP_WITH_PREFIX), peek_one)

	def test_peek_is_empty_without_a_prefix(self):
		self.assertEqual(peek_next_code(GROUP_NO_PREFIX), "")

	def test_generate_is_empty_without_a_prefix(self):
		self.assertEqual(generate_code(GROUP_NO_PREFIX), "")

	def test_counter_skips_codes_that_already_exist(self):
		"""An import that wrote codes without touching tabSeries leaves the
		counter behind reality; generation must skip forward, not collide."""
		taken = peek_next_code(GROUP_WITH_PREFIX)
		self._new_item(GROUP_WITH_PREFIX, item_code=taken)
		self.assertNotEqual(generate_code(GROUP_WITH_PREFIX), taken)
