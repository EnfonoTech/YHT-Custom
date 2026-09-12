# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Tests for the form trimming.

The regression these guard against is specific and was live for a week: the price
list was relocated on Sales Invoice, Delivery Note and Purchase Invoice but NOT on
Sales Order, Quotation or Purchase Receipt — where it was still sitting inside the
`Currency and Price List` accordion. Hiding that accordion, which is what makes the
screens clean, would therefore have hidden the price list on those three.

So the two facts are tested together: the section is hidden AND the price list is
outside it.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint, cstr

from yht_custom.form_layout import (
	GROUP_BEFORE,
	HIDE_FIELDS,
	_CURRENCY_SECTION,
	setup_form_layout,
)

PRICE_LIST_FIELD = {
	"Sales Invoice": "selling_price_list",
	"Sales Order": "selling_price_list",
	"Delivery Note": "selling_price_list",
	"Quotation": "selling_price_list",
	"Purchase Invoice": "buying_price_list",
	"Purchase Receipt": "buying_price_list",
}


class TestFormLayout(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		setup_form_layout()
		frappe.clear_cache()

	def test_every_hidden_field_exists(self):
		"""A fieldname that does not exist is hidden silently and forever — the
		Property Setter is written, nothing errors, and the field it was meant to
		hide stays visible. Two such typos shipped on this app before."""
		for doctype, fieldnames in HIDE_FIELDS.items():
			if not frappe.db.exists("DocType", doctype):
				continue
			meta = frappe.get_meta(doctype)
			for fieldname in fieldnames:
				self.assertIsNotNone(
					meta.get_field(fieldname), f"{doctype}.{fieldname} does not exist in this version"
				)

	def test_every_move_anchor_exists(self):
		"""`update_stock` exists only on Sales Invoice and Purchase Invoice, and
		Quotation has no header warehouse at all, so the anchors legitimately
		differ per doctype. A wrong anchor is a silent no-op."""
		# MOVE_AFTER was retired when client-sheet item 10 landed: it and the new
		# rule both rewrote `field_order` and each undid the other on every
		# migrate. GROUP_BEFORE is the single rule now.
		for doctype, (group, anchor) in GROUP_BEFORE.items():
			if not frappe.db.exists("DocType", doctype):
				continue
			meta = frappe.get_meta(doctype)
			self.assertIsNotNone(meta.get_field(anchor), f"{doctype}.{anchor} (anchor)")
			present = [f for f in group if meta.get_field(f)]
			self.assertTrue(present, f"{doctype}: none of {group} exists")

	def test_currency_section_is_hidden_everywhere(self):
		for doctype in PRICE_LIST_FIELD:
			if not frappe.db.exists("DocType", doctype):
				continue
			field = frappe.get_meta(doctype).get_field("currency_and_price_list")
			self.assertIsNotNone(field, doctype)
			self.assertTrue(field.hidden, f"{doctype}: the Currency and Price List section is visible")

	def test_price_list_is_outside_the_hidden_section(self):
		"""THE ONE THAT MATTERS. Hiding a Section Break hides everything between it
		and the next section break, so a price list left inside disappears."""
		for doctype, price_field in PRICE_LIST_FIELD.items():
			if not frappe.db.exists("DocType", doctype):
				continue
			meta = frappe.get_meta(doctype)
			order = [df.fieldname for df in meta.fields]
			self.assertIn(price_field, order, doctype)

			start = order.index("currency_and_price_list")
			inside = []
			for fieldname in order[start + 1 :]:
				field = meta.get_field(fieldname)
				if field and field.fieldtype in ("Section Break", "Tab Break"):
					break
				inside.append(fieldname)

			self.assertNotIn(
				price_field,
				inside,
				f"{doctype}: {price_field} is still inside the hidden Currency and Price List section",
			)

	def test_price_list_is_visible(self):
		for doctype, price_field in PRICE_LIST_FIELD.items():
			if not frappe.db.exists("DocType", doctype):
				continue
			field = frappe.get_meta(doctype).get_field(price_field)
			self.assertFalse(field.hidden, f"{doctype}.{price_field} is hidden")

	def test_price_list_sits_in_the_group_above_the_items(self):
		"""The price list travels with update-stock and the store, in its own
		section, immediately above the item table.

		Replaces an older assertion that the price list sat immediately AFTER a
		per-doctype anchor. That rule (MOVE_AFTER) was retired when client-sheet
		item 10 landed: it and the new grouping both rewrote `field_order` and each
		undid the other on every migrate.
		"""
		for doctype, (group, anchor) in GROUP_BEFORE.items():
			if not frappe.db.exists("DocType", doctype):
				continue
			with self.subTest(doctype=doctype):
				order = [df.fieldname for df in frappe.get_meta(doctype).fields]
				present = [f for f in group if f in order]
				self.assertIn(anchor, order)
				at = order.index(anchor)
				self.assertEqual(
					order[at - len(present) : at],
					present,
					f"{doctype}: {present} is not contiguous immediately before {anchor}",
				)

	def test_the_group_opens_its_own_visible_section(self):
		"""🔴 The regression that made this necessary.

		Sales Invoice and Quotation have NO section break between the hidden
		`Currency and Price List` accordion and the items table. Moving the group to
		sit just before `items_section` put it inside the hidden span, so update
		stock, the price list and the store all vanished from the form. The group
		now LEADS with its own Section Break custom field.
		"""
		for doctype, (group, _anchor) in GROUP_BEFORE.items():
			if not frappe.db.exists("DocType", doctype):
				continue
			with self.subTest(doctype=doctype):
				self.assertEqual(
					group[0],
					"custom_stock_pricing_section",
					f"{doctype}: the group must open with its own section break",
				)
				field = frappe.get_meta(doctype).get_field("custom_stock_pricing_section")
				self.assertIsNotNone(field, f"{doctype}: section break was never created")
				self.assertEqual(field.fieldtype, "Section Break")
				self.assertFalse(field.hidden, f"{doctype}: the group's own section is hidden")

	def test_section_members_are_hidden_individually_too(self):
		"""Belt and braces: hiding the section break is enough for the form, but a
		report column, a search or a print format can still reach a field whose own
		`hidden` is 0."""
		for fieldname in _CURRENCY_SECTION:
			for doctype in PRICE_LIST_FIELD:
				if not frappe.db.exists("DocType", doctype):
					continue
				field = frappe.get_meta(doctype).get_field(fieldname)
				if not field:
					continue
				self.assertTrue(field.hidden, f"{doctype}.{fieldname}")

	def test_is_idempotent(self):
		"""Runs on every after_migrate, so a second run must change nothing."""
		before = frappe.db.count("Property Setter")
		setup_form_layout()
		self.assertEqual(frappe.db.count("Property Setter"), before)


# ---------------------------------------------------------------- batch 3
#
# Client sheet batch 3 adds four configuration items to this module (24 title =
# voucher number · 25 update-stock default · 33 the Payment Entry tax block · 36
# the return split filter) plus an `Address` entry to HIDE_FIELDS (item 29).
#
# The spec's Test Plan asks for exactly two things here, and both are extensions
# of what this file already does rather than new ideas:
#
#   1. Every fieldname in every NEW map exists on live meta. STRICT — a missing
#      field fails, it does not skip. Two such typos have already shipped on this
#      app, and the failure mode is silence: the Property Setter is written, the
#      migrate reports success, and the field it names stays exactly as it was.
#   2. `test_is_idempotent` still holds once the new steps run. `after_migrate`
#      runs all of them on every deploy, so a second pass must create nothing.
#
# The new names are resolved LAZILY. A module-level
# `from yht_custom.form_layout import setup_title_as_voucher_no` would abort
# collection of this whole file the moment one of the four is missing, taking the
# ten tests above down with it — the same "one failure hides another" shape that
# `PROVISIONING_STEPS` was split up to avoid.

#: The exact field sets the spec enumerates, written down here rather than read
#: back out of `form_layout` — a test that imports the constant it is checking
#: proves only that the module imports (recorded gotcha 58).
BATCH3_FIELDS = {
	"Address": (
		# item 29 hides
		"email_id", "phone", "fax",
		# gated rather than hidden — it must still exist for the gate to reach it
		"address_title",
		# and the fields the reorder names, which must all still exist
		"address_type", "address_line1", "address_line2", "pincode", "city", "country",
		"column_break0",
		"custom_short_address", "custom_building_number", "custom_additional_number",
		"custom_area", "custom_address_line1_arabic", "custom_area_arabic",
		"custom_city_arabic", "custom_country_arabic",
	),
	"Payment Entry": (
		# item 33 — the three gated Section Breaks
		"taxes_and_charges_section", "section_break_56", "section_break_60",
		# the three hidden outright
		"purchase_taxes_and_charges_template", "apply_tax_withholding_amount",
		"tax_withholding_category",
		# and everything the item deliberately leaves alone, which still has to be
		# real or the assertion that it survived is vacuous
		"sales_taxes_and_charges_template", "column_break_55", "taxes",
		"base_total_taxes_and_charges", "column_break_61", "total_taxes_and_charges",
		"deductions_or_loss_section", "deductions", "custom_prepayment_invoice",
	),
	# item 25
	"Sales Invoice": ("update_stock", "is_return"),
	"Purchase Invoice": ("update_stock", "is_return"),
	# item 36 — the existing Check, on the two remaining lists
	"Delivery Note": ("is_return",),
	"Purchase Receipt": ("is_return",),
}

#: item 24. Eight doctypes, and the property is DocType-level.
BATCH3_TITLE_DOCTYPES = (
	"Sales Invoice", "Sales Order", "Delivery Note", "Quotation",
	"Purchase Invoice", "Purchase Receipt", "Payment Entry", "Journal Entry",
)

#: `setup_title_as_voucher_no` is deliberately ABSENT. Item 24's mechanism was
#: withdrawn — `title_field = "name"` empties every transaction list — and the
#: function now throws when called, so an idempotency harness that ran it would
#: error rather than measure anything. `test_client_sheet_batch3
#: .TestBatch3Wiring.test_the_withdrawn_item_24_step_is_not_wired` asserts both
#: halves (out of PROVISIONING_STEPS, and refuses to run).
BATCH3_STEPS = (
	"setup_update_stock_default",
	"setup_payment_entry_tax_block",
	"setup_return_split_filter",
)


def _step(name):
	"""One batch-3 step, failing ONE test rather than the file."""
	from yht_custom import form_layout

	func = getattr(form_layout, name, None)
	if func is None:
		raise AssertionError(f"form_layout.{name} is not implemented yet")
	return func


class TestFormLayoutBatch3Maps(FrappeTestCase):
	"""Strict existence for every fieldname batch 3 configures."""

	def test_every_batch3_fieldname_exists_on_live_meta(self):
		"""STRICT. `_set_property` writes a Property Setter for a fieldname that
		does not exist without complaining, and `frappe.get_meta` then has nothing
		to apply it to. The change looks done and is not — it was live for a week
		last time, and it is the single most repeated defect on this app.

		`section_break_56` and `section_break_60` matter most: those are auto-named
		by position and a version bump renumbers them, so they are checked against
		LIVE meta rather than against upstream JSON.
		"""
		for doctype, fieldnames in BATCH3_FIELDS.items():
			self.assertTrue(
				frappe.db.exists("DocType", doctype),
				f"{doctype} does not exist on this site — the whole map is dead",
			)
			meta = frappe.get_meta(doctype)
			for fieldname in fieldnames:
				with self.subTest(doctype=doctype, fieldname=fieldname):
					self.assertIsNotNone(
						meta.get_field(fieldname),
						f"{doctype}.{fieldname} does not exist in this version",
					)

	def test_the_address_entry_was_actually_added_to_hide_fields(self):
		"""Without this, `test_every_hidden_field_exists` above passes vacuously —
		it iterates HIDE_FIELDS, so a missing "Address" key is simply not checked.
		Item 29 routes through HIDE_FIELDS precisely so the strict test covers it,
		and that only works if the key is there."""
		self.assertIn("Address", HIDE_FIELDS, "item 29 did not go through HIDE_FIELDS")
		for fieldname in ("email_id", "phone", "fax"):
			with self.subTest(fieldname=fieldname):
				self.assertIn(fieldname, HIDE_FIELDS["Address"])
		# `address_title` is deliberately NOT hidden — hiding it outright makes a
		# link-less new Address unsaveable, refused by `Address.validate` pointing
		# at a field that is not on the screen. It is gated on the Short Address
		# instead; `form_layout.ADDRESS_TITLE_GATE` owns that and
		# `test_client_sheet_batch3` asserts the save.
		self.assertNotIn("address_title", HIDE_FIELDS["Address"])

	def test_every_doctype_in_a_new_map_exists(self):
		"""A doctype name typo is the same silent no-op one level up: the loop skips
		it and nothing is configured."""
		for doctype in set(BATCH3_FIELDS) | set(BATCH3_TITLE_DOCTYPES):
			with self.subTest(doctype=doctype):
				self.assertTrue(frappe.db.exists("DocType", doctype))

	def test_every_flat_field_map_in_the_module_names_real_fields(self):
		"""A GENERIC sweep, so a map added later is covered without editing a test.

		Catches any module-level `{doctype: [fieldname, ...]}` constant — the shape
		HIDE_FIELDS uses and the shape the new maps are most likely to take. Maps
		with a different shape (GROUP_BEFORE, which holds `(group, anchor)`) are
		skipped here and covered by their own test above.
		"""
		from yht_custom import form_layout

		checked = 0
		for name, value in sorted(vars(form_layout).items()):
			if name.startswith("_") or not isinstance(value, dict) or not value:
				continue
			for doctype, fieldnames in value.items():
				if not isinstance(doctype, str) or not frappe.db.exists("DocType", doctype):
					continue
				if not isinstance(fieldnames, list | tuple) or not fieldnames:
					continue
				if not all(isinstance(f, str) for f in fieldnames):
					continue  # not a flat field list — a different shape
				meta = frappe.get_meta(doctype)
				for fieldname in fieldnames:
					checked += 1
					with self.subTest(constant=name, doctype=doctype, fieldname=fieldname):
						self.assertIsNotNone(
							meta.get_field(fieldname),
							f"{name}[{doctype!r}] names {fieldname}, which does not exist",
						)
		self.assertTrue(checked, "the sweep found no flat field maps at all — it is not working")


class TestFormLayoutBatch3Idempotency(FrappeTestCase):
	"""`after_migrate` runs every step on every deploy, so a second pass must not
	create a single new Property Setter. This is the existing `test_is_idempotent`
	extended to the four new steps — together, in the order `after_migrate` runs
	them, because a pair of steps that each undo the other is idempotent
	individually and thrashes on every migrate as a set."""

	def test_the_new_steps_are_individually_idempotent(self):
		for name in BATCH3_STEPS:
			with self.subTest(step=name):
				step = _step(name)
				step()
				frappe.clear_cache()
				before = frappe.db.count("Property Setter")
				step()
				self.assertEqual(
					frappe.db.count("Property Setter"),
					before,
					f"{name} wrote a new Property Setter on its second run",
				)

	def test_the_whole_set_is_idempotent_together(self):
		"""🔴 Two steps that each rewrite the other's row are individually
		idempotent and still thrash on every migrate. `MOVE_AFTER` and
		`GROUP_BEFORE` did exactly that on this app until MOVE_AFTER was retired,
		so this is a measured failure mode, not a hypothetical one."""
		steps = [setup_form_layout] + [_step(name) for name in BATCH3_STEPS]
		for step in steps:
			step()
		frappe.clear_cache()

		before = frappe.db.count("Property Setter")
		snapshot = {
			row.name: row.value
			for row in frappe.get_all("Property Setter", fields=["name", "value"])
		}

		for step in steps:
			step()
		frappe.clear_cache()

		self.assertEqual(
			frappe.db.count("Property Setter"), before, "a second full pass created new rows"
		)
		after = {
			row.name: row.value
			for row in frappe.get_all("Property Setter", fields=["name", "value"])
		}
		changed = {k: (snapshot.get(k), v) for k, v in after.items() if snapshot.get(k) != v}
		self.assertFalse(changed, f"a second full pass rewrote existing rows: {changed}")

	def test_the_existing_form_layout_step_still_settles_after_the_new_ones(self):
		"""The original `test_is_idempotent`, re-run with the batch-3 steps in
		between. If a new step touches `field_order` or a shared doctype property,
		`setup_form_layout` will write again on the next migrate and this catches
		it."""
		setup_form_layout()
		for name in BATCH3_STEPS:
			_step(name)()
		before = frappe.db.count("Property Setter")
		setup_form_layout()
		self.assertEqual(frappe.db.count("Property Setter"), before)


class TestCustomizeFormStaysSaveable(FrappeTestCase):
	"""🔴 THE INVARIANT THIS FILE EXISTED WITHOUT, AND IT COST A BLOCKED FORM.

	`DocType.validate_fields` refuses *"Field <X> cannot be hidden and mandatory
	without default"* — and it refuses the WHOLE form, not just that field. So one
	hidden + mandatory + defaultless field makes EVERY unrelated Customize Form
	change on that doctype impossible to save.

	It went unnoticed for weeks because this app writes Property Setters directly
	and never passes through that validation. Only a human opening Customize Form
	and pressing Update ever meets it — which is exactly what happened on
	production, on six doctypes at once, via `currency` and `conversion_rate`.

	Asserted against HIDE_FIELDS itself, so a field hidden in future is covered
	without anyone remembering this.
	"""

	def test_no_hidden_field_is_mandatory_without_a_default(self):
		from yht_custom.form_layout import HIDE_FIELDS

		offenders = []
		for doctype in HIDE_FIELDS:
			if not frappe.db.exists("DocType", doctype):
				continue
			meta = frappe.get_meta(doctype)
			for fieldname in HIDE_FIELDS[doctype]:
				field = meta.get_field(fieldname)
				if not field:
					continue
				if cint(field.hidden) and cint(field.reqd) and not cstr(field.default).strip():
					offenders.append(f"{doctype}.{fieldname}")

		self.assertFalse(
			offenders,
			"hidden + mandatory + no default — Customize Form cannot be saved on "
			f"these doctypes at all: {offenders}",
		)


class TestTaxesBlockIsBackOnSalesInvoice(FrappeTestCase):
	"""Client reversal, 2026-09-12. Measured: 150 of 2,460 submitted invoices carry
	no tax template, so the picker is needed for the zero-rated / export / return
	cases the original hiding traded away."""

	def test_the_taxes_section_is_visible_again(self):
		from yht_custom.form_layout import _TAXES_NOW_VISIBLE

		meta = frappe.get_meta("Sales Invoice")
		for fieldname in _TAXES_NOW_VISIBLE:
			with self.subTest(fieldname=fieldname):
				field = meta.get_field(fieldname)
				self.assertTrue(field, f"Sales Invoice has no {fieldname}")
				self.assertFalse(cint(field.hidden), f"{fieldname} is still hidden")

	def test_the_three_unused_fields_stay_hidden(self):
		"""Used on 0 invoices, and they are the noise the client asked to remove."""
		from yht_custom.form_layout import _TAXES_NOISE

		meta = frappe.get_meta("Sales Invoice")
		for fieldname in _TAXES_NOISE:
			with self.subTest(fieldname=fieldname):
				self.assertTrue(cint(meta.get_field(fieldname).hidden), f"{fieldname} is visible")

	def test_the_default_tax_template_still_carries_the_vat(self):
		"""Un-hiding the picker adds a choice; it must not have removed automation."""
		company = frappe.defaults.get_global_default("company")
		self.assertTrue(
			frappe.db.get_value(
				"Sales Taxes and Charges Template", {"company": company, "is_default": 1}, "name"
			),
			"no default sales tax template — VAT would now depend on the operator",
		)
