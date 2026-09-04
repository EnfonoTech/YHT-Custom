# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Client sheet (Openarabia Team) — batch 2: client prints & the HTML letterhead.

Encodes every check in `.pipeline/spec.md` rev2 "Test Plan" (checks 1-59). Check
numbers appear as `# check N` markers so the spec and this file can be diffed by
eye.

READ ONLY, with two deliberate exceptions that `FrappeTestCase` rolls back: the
branch-user fixture (check 35) and the live-Bank-Account edit (check 39). Nothing
here is saved to a submitted document; the degenerate-document tests mutate an
in-memory copy and render it, they never call `save()`.

Run:

    bench --site yht-test run-tests --app yht_custom \
        --module yht_custom.tests.test_katc_prints --skip-before-tests

`--skip-before-tests` is mandatory on every run — `hrms`'s `before_tests` hook
deleted 4,847 client `Item Price` rows once already. Never run on
`yht-khobhar.enfonoerp.com` (`allow_tests` is false there by design).

--------------------------------------------------------------------------------
STRUCTURAL CONTRACTS THIS SUITE IMPOSES ON THE IMPLEMENTATION
--------------------------------------------------------------------------------
Several spec checks ("strip the letterhead block and compare", "strip the Arabic
column and compare", "the JS passes no_letterhead=1 on exactly three paths")
cannot be asserted without agreeing on a marker. The three markers are:

1. Every format's outer page table opens with ONE `<thead>` holding either
   `{{ letter_head }}` or the spacer. It must be the FIRST `<thead>` in the
   rendered output — checks 20 and 54 strip it by that position.
2. The `No LH` spacer carries an inline `height: <N>pt` where N is
   `katc_letterhead.NO_LH_SPACER_PT` — ONE constant, reached from the formats
   through `yht_katc_spacer_pt()` and imported here, never a literal. It is the
   height that lands the rendered body at or below the absolute first-glyph y of
   every without-letterhead artefact (deepest: `Invoice Print 2`, 172.40 pt), so
   the body clears the pre-printed stationery. NOT the artefacts' 24 pt DROP —
   see the constant's own comment — check 25.
3. `KATC Quotation Arabic`'s extra column carries `class="katc-ar-col"` on both
   its `<th>` and its `<td>` — check 26 strips it by that class.
4. `katc_print_buttons.js` expresses its button map as FLAT object literals
   carrying `format:`, `no_letterhead:` and (with-letterhead only) `letterhead:`
   keys — check 48 parses them.
"""

import os
import re
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cstr, flt

from yht_custom import letterhead, print_helpers, setup

ARABIC = re.compile(r"[؀-ۿ]")

#: The one HTML letterhead this change ships. Duplicated from the spec on
#: purpose — check 43 proves the implementation agrees with it.
EXPECTED_LETTER_HEAD = "KATC Letterhead"

#: The client's incumbent image letterhead. 1,515 Sales Invoices reference it.
INCUMBENT_LETTER_HEAD = "KATHOOM ALKHOBAR"
INCUMBENT_IMAGE = "/files/KhobarHeading1.jpg"

#: 1,266 documents point at this. It does not exist; frappe degrades quietly.
DANGLING_LETTER_HEAD = "Kathoom without letterhead"

LOGO_URL = "/assets/yht_custom/images/katc_logo.jpg"
LOGO_MAX_BYTES = 60 * 1024

#: Literal facts from `.pipeline/client-artefacts/Kathoom_A4_Letterhead_Only.html`.
#: Deliberately NOT derived from Company/Address — the artefact is the spec.
ARTEFACT_VAT = "311264592800003"
ARTEFACT_CR = "2051226328"
ARTEFACT_COMPANY_AR = "شركة كتوم الخبر التجارية"

#: The receiving account the artefacts actually print (OQ-1).
ARTEFACT_BANK = "AL RAJHI BANK"
ARTEFACT_IBAN = "SA6880000139608013397744"
ARTEFACT_ACCOUNT_NO = "139000010006083397744"

#: (print format, doctype). All ten.
FORMATS = (
	("KATC Delivery Note", "Delivery Note"),
	("KATC Tax Invoice", "Sales Invoice"),
	("KATC Proforma Invoice", "Sales Order"),
	("KATC Sales Order", "Sales Order"),
	("KATC Sales Order Arabic", "Sales Order"),
	("KATC Sales Order No LH", "Sales Order"),
	("KATC Quotation", "Quotation"),
	("KATC Quotation No LH", "Quotation"),
	("KATC Quotation Arabic", "Quotation"),
	("KATC Quotation Proforma", "Quotation"),
)

#: Formats whose whole body is a two-line shim over a shared template. A variant is a
#: FLAG, not a copy — see yht_custom/templates/includes/katc/.
SHIMMED = (
	"KATC Quotation",
	"KATC Quotation Arabic",
	"KATC Proforma Invoice",
	"KATC Quotation Proforma",
	"KATC Sales Order",
	"KATC Sales Order Arabic",
	"KATC Sales Order No LH",
)

#: The pair that is ONE format toggled by `no_letterhead` (Q2).
TOGGLED = (
	("KATC Delivery Note", "Delivery Note"),
	("KATC Tax Invoice", "Sales Invoice"),
)

#: The two formats that must never render `{{ letter_head }}` at all.
NO_LH_FORMATS = (
	("KATC Sales Order No LH", "Sales Order"),
	("KATC Quotation No LH", "Quotation"),
)

#: Formats whose BODY is bilingual (check 12).
ARABIC_BODY_FORMATS = (
	"KATC Delivery Note",
	"KATC Tax Invoice",
	"KATC Proforma Invoice",
	"KATC Quotation No LH",
	"KATC Quotation Arabic",
)

#: The English-body layouts — assert their titles, not their script (check 12).
ENGLISH_BODY_TITLES = {
	"KATC Sales Order No LH": "SALES ORDER",
	"KATC Quotation": "Quotation",
}

#: The documents the client's artefact PDFs were rendered from (check 53).
ARTEFACT_DOCS = {
	"Delivery Note": "KSDN-26-0589",
	"Sales Invoice": "KSIN-26-0639",
	"Sales Order": "KSSO-26-0569",
	"Quotation": "KSSQ-26-0897",
}

#: Step 4, measured on `yht-test`. Child row first, per parent doctype.
CHILD_ARABIC_FIELDS = {
	"Sales Invoice Item": ("custom_item_arabic_name", "item_arabic_name"),
	"Quotation Item": ("custom_item_name_in_arabic",),
	"Delivery Note Item": ("custom_item_name_in_arabic",),
	"Sales Order Item": ("custom_item_name_in_arabic",),
}

#: The six formats this change must leave completely alone.
INCUMBENT_FORMATS = (
	("YHT Delivery Note", "Delivery Note"),
	("YHT Sales Order", "Sales Order"),
	("YHT Quotation", "Quotation"),
	("YHT Purchase Invoice", "Purchase Invoice"),
	("YHT Expense Invoice", "Purchase Invoice"),
	("YHT Journal Entry", "Journal Entry"),
)

BUTTON_DOCTYPES = ("Delivery Note", "Sales Invoice", "Sales Order", "Quotation")

#: New jinja helpers this change adds. Every one must be registered AND resolve —
#: an unresolved jinja path 500s every website page, /login included (gotcha 25).
NEW_JINJA_METHODS = (
	"yht_custom.print_helpers.yht_katc_lh",
	"yht_custom.print_helpers.yht_katc_email",
	"yht_custom.print_helpers.yht_katc_spacer_pt",
	"yht_custom.print_helpers.yht_company_vat",
	"yht_custom.print_helpers.yht_row_taxes",
	"yht_custom.print_helpers.yht_national_address",
	"yht_custom.print_helpers.yht_sales_person",
	"yht_custom.print_helpers.yht_creator_contact",
	"yht_custom.print_helpers.yht_zatca_qr",
	"yht_custom.print_helpers.yht_bank_details",
)

NATIONAL_ADDRESS_KEYS = {
	"building",
	"street",
	"district",
	"city",
	"pincode",
	"additional",
	"country",
}


# --------------------------------------------------------------------- helpers


def katc_letterhead():
	"""Imported lazily so a missing module fails ONE test, not the whole file."""
	from yht_custom import katc_letterhead as module

	return module


def helper(name):
	"""Fetch a print helper by name, failing with a readable message if absent."""
	func = getattr(print_helpers, name, None)
	if func is None:
		raise AssertionError(f"print_helpers.{name} does not exist")
	return func


def submitted(doctype):
	"""The NEWEST submitted document, deterministically.

	🔴 `order_by` is load-bearing, not tidiness. Without it `get_value` returns
	whichever row MariaDB happens to hand back, so every check that falls through
	to this helper runs against an arbitrary document and a re-run can exercise a
	different one — a suite that is not reproducible on exactly the paths where it
	is substituting for a missing artefact.
	"""
	return frappe.db.get_value(doctype, {"docstatus": 1}, "name", order_by="creation desc")


def artefact_or_any(doctype):
	"""The artefact document if it is on this site, else the newest submitted one.

	Only `KSSO-26-0569` is on `yht-test`; `KSDN-26-0589`, `KSIN-26-0639` and
	`KSSQ-26-0897` are not, so three of the four fidelity paths run against a
	substitute. The substitute is at least the same one every run — the
	document-for-document diff against the three real artefacts needs the client
	site and is a DELIVER task, not something a test on this site can hold.
	"""
	name = ARTEFACT_DOCS.get(doctype)
	if name and frappe.db.exists(doctype, name):
		return name
	return submitted(doctype)


def render(doctype, name, print_format, **kwargs):
	return frappe.get_print(doctype, name, print_format=print_format, **kwargs)


def squash(html):
	"""Collapse whitespace so two renders can be compared for real difference."""
	return re.sub(r"\s+", " ", html or "").strip()


def format_body(html):
	"""The print format's own output, without the printview PAGE around it.

	`frappe.get_print` renders `frappe/www/printview.html`, and its `.action-banner`
	"Get PDF" anchor echoes `format=`, `letterhead=`, `no_letterhead=` and `_lang=`
	straight back out — the very arguments checks 20 and 26 vary. Comparing two raw
	pages therefore can never succeed no matter how identical the formats are.
	Everything from `<div class="print-format-gutter">` onwards is the format and
	nothing else (verified against the template on the bench).
	"""
	html = html or ""
	for marker in ('<div class="print-format-gutter"', '<div class="print-format"'):
		index = html.find(marker)
		if index != -1:
			return html[index:]
	return html


def money_value(cell):
	"""The number out of one rendered money cell, or `None`.

	`yht_money` goes through `fmt_money`, so the cell carries a currency symbol and
	thousands separators around it.
	"""
	text = re.sub(r"<[^>]+>", " ", cell or "")
	match = re.search(r"(-?[\d,]+\.\d{2})", text)
	return flt(match.group(1).replace(",", "")) if match else None


def strip_first_thead(html):
	"""Remove the outer page table's `<thead>` — the letterhead / spacer cell.

	The items table also has a `<thead>`; the outer one is always first, which is
	exactly what makes the header repeat on page 2.
	"""
	return re.sub(r"<thead\b.*?</thead>", "", html or "", count=1, flags=re.S | re.I)


def format_source(print_format: str) -> str:
	"""The format's EFFECTIVE template source, with any `{% include %}` resolved.

	A Print Format record is now a two-line shim over a shared template, so grepping
	the stored `html` for markup finds the include statement and nothing else. Every
	check that asks "does this format contain X" has to look where X actually lives.
	"""
	import os

	html = frappe.db.get_value("Print Format", print_format, "html") or ""
	app_parent = os.path.dirname(frappe.get_app_path("yht_custom"))
	for path in re.findall(r'{%-?\s*include\s+"([^"]+)"', html):
		full = os.path.join(app_parent, path)
		if os.path.exists(full):
			html += "\n" + open(full, encoding="utf-8").read()
	return html


def plain_arabic(html: str) -> str:
	"""Undo the bidi anchoring so a plain-string search still finds a label.

	Every Arabic literal is RLM-wrapped and NBSP-joined (the engine mis-anchors a
	right-aligned RTL line otherwise), so `assertIn("فاتورة ضريبية", html)` misses
	text that IS on the page. Normalise the haystack, not the assertion.
	"""
	return (html or "").replace("\u200f", "").replace("\u00a0", " ")


def strip_column_widths(html: str) -> str:
	"""Drop `width:N%` declarations so two column sets can be compared.

	The Arabic variant pins EVERY column width; the plain one lets Item Name size
	itself. That is deliberate — auto layout is what let the Arabic spill over the
	Quantity figures — so it is a third expected difference, not a divergence.
	"""
	return re.sub(r'\s*style="width:\s*[0-9.]+%\s*"', "", html or "", flags=re.I)


def strip_bank_block(html: str) -> str:
	"""Remove the VAT / bank block so two formats can be compared without it."""
	return re.sub(r'<div class="katc-bank">.*?</div>', "", html, flags=re.S)


def strip_arabic_column(html):
	"""Remove the Arabic item names so two formats can be compared without them.

	⚠️ It used to strip whole `katc-ar-col` CELLS. The Arabic is no longer a column —
	this engine will not wrap an RTL run inside a sized cell, and 71% of the client's
	Arabic names are too long for one — so it is now a `katc-ar` div inside the item
	cell, the same shape the Tax Invoice and Delivery Note have always used.
	"""
	html = re.sub(
		r"<t([hd])\b[^>]*katc-ar-col[^>]*>.*?</t\1>", "", html or "", flags=re.S | re.I
	)
	return re.sub(r'<div class="katc-ar">.*?</div>', "", html, flags=re.S)


def js_source():
	path = frappe.get_app_path("yht_custom", "public", "js", "katc_print_buttons.js")
	if not os.path.exists(path):
		raise AssertionError(f"{path} does not exist")
	with open(path, encoding="utf-8") as fh:
		return fh.read()


#: A flat `{ … format: "X" … }` object literal in the button JS.
_BUTTON_LITERAL = re.compile(r"\{[^{}]*?format\s*:\s*[\"'][^\"']+[\"'][^{}]*?\}", re.S)


def button_specs(source):
	"""Parse the button map out of the JS (contract 4 in the module docstring)."""
	specs = []
	for block in _BUTTON_LITERAL.findall(source):
		fmt = re.search(r"format\s*:\s*[\"']([^\"']+)[\"']", block)
		no_lh = re.search(r"no_letterhead\s*:\s*[\"']?(\d)[\"']?", block)
		lh = re.search(r"letterhead\s*:\s*([\"'][^\"']*[\"']|[A-Za-z_$][\w.$]*)", block)
		specs.append(
			{
				"format": fmt.group(1) if fmt else None,
				"no_letterhead": no_lh.group(1) if no_lh else None,
				"letterhead": lh.group(1) if lh else None,
				"raw": block,
			}
		)
	return specs


# ================================================================= letterhead


class TestKatcLetterhead(FrappeTestCase):
	"""Checks 1-9. One HTML Letter Head, and nothing else disturbed."""

	def test_the_record_exists_and_is_never_the_default(self):
		# check 1
		module = katc_letterhead()
		self.assertEqual(module.KATC_LETTER_HEAD, EXPECTED_LETTER_HEAD)
		self.assertTrue(
			frappe.db.exists("Letter Head", module.KATC_LETTER_HEAD),
			f"{module.KATC_LETTER_HEAD} was never provisioned",
		)
		row = frappe.db.get_value(
			"Letter Head",
			module.KATC_LETTER_HEAD,
			["source", "disabled", "is_default"],
			as_dict=True,
		)
		self.assertEqual(row.source, "HTML", "an image letterhead cannot be bilingual")
		self.assertFalse(row.disabled)
		self.assertFalse(
			row.is_default,
			"is_default=1 would silently change how 1,515 historical invoices print",
		)

	def test_provisioning_never_takes_the_default_on_a_site_with_none(self):
		"""check 1, the branch `db_set` cannot repair.

		`validate_disabled_and_default` forces `is_default = 1` on save when no
		Letter Head holds it (`letter_head.py:55-57`), and `on_update`'s
		`set_as_default()` then clears the flag on every OTHER record and writes
		the global `set_default("letter_head", …)` (`:118-127`). A following
		`db_set("is_default", 0)` puts back one column and neither of those. Not
		reachable on `yht-khobhar` — `KATHOOM ALKHOBAR` holds the flag — so this
		takes the flag away first, and puts it back in a `finally`.

		🔴 THE RESTORE IS NOT TIDINESS. `FrappeTestCase` registers its rollback with
		`addClassCleanup(_rollback_db)` (`frappe/tests/utils.py:46`), so it runs once
		per CLASS, not once per test: anything left behind here is still there when
		the next method in this class reads it, and two of them assert on exactly
		these columns.
		"""
		module = katc_letterhead()
		defaults = frappe.get_all("Letter Head", filters={"is_default": 1}, pluck="name")
		try:
			for name in defaults:
				frappe.db.set_value("Letter Head", name, "is_default", 0, update_modified=False)
			# Make the update branch WANT to save, or the comparison short-circuits
			# to `unchanged` and nothing is exercised.
			frappe.db.set_value(
				"Letter Head", module.KATC_LETTER_HEAD, "source", "Image", update_modified=False
			)

			module.setup_katc_letterhead()

			# Read the row `set_default` writes rather than `frappe.db.get_default`,
			# which is served out of a cache this test would have to invalidate
			# through a private helper (`frappe.defaults` exposes no `clear_cache`).
			self.assertNotEqual(
				frappe.db.get_value(
					"DefaultValue", {"parent": "__default", "defkey": "letter_head"}, "defvalue"
				),
				module.KATC_LETTER_HEAD,
				f"{module.KATC_LETTER_HEAD} became the site-wide default Letter Head",
			)
			self.assertFalse(
				frappe.db.get_value("Letter Head", module.KATC_LETTER_HEAD, "is_default"),
				"is_default was taken on a site with no other default",
			)
			self.assertEqual(
				frappe.db.get_value("Letter Head", module.KATC_LETTER_HEAD, "source"),
				"HTML",
				"the guarded branch must still repair the record",
			)
		finally:
			for name in defaults:
				frappe.db.set_value("Letter Head", name, "is_default", 1, update_modified=False)
			frappe.db.set_value(
				"Letter Head", module.KATC_LETTER_HEAD, "source", "HTML", update_modified=False
			)

	def test_the_spacer_is_not_emitted_on_the_plain_desk_print_path(self):
		"""🔴 THE DESK `Print` MENU PASSES NO `letterhead=` AT ALL.

		The five with-letterhead formats gate their header cell on
		`'katc-lh' in letter_head`. When a user opens the standard print view the
		argument is absent, or resolves to the incumbent IMAGE letterhead, and
		neither contains that marker — so an unconditional `{% else %}` put a
		194 pt (68 mm) blank band at the top of the page on the one path nobody
		passes arguments on. The spacer exists for `Print Without LH`, so it is
		gated on `no_letterhead`, which `printview.get_rendered_template` puts in
		the template args (`frappe/www/printview.py:234`, coerced at `:128-131`).

		Every other render in this suite passes `letterhead=EXPECTED_LETTER_HEAD`,
		which is exactly why this path was uncovered.
		"""
		spacer = re.compile(r"katc-spacer", re.I)
		for print_format, doctype in FORMATS:
			if (print_format, doctype) in NO_LH_FORMATS:
				continue  # these two are ALWAYS spacer-only, by design
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			with self.subTest(print_format=print_format):
				# No letterhead= and no no_letterhead= — the desk Print menu.
				body = format_body(render(doctype, name, print_format))
				self.assertIsNone(
					spacer.search(body),
					f"{print_format} prints a blank spacer band on the plain desk print path",
				)

	def test_provisioning_never_takes_the_default_when_it_has_to_INSERT(self):
		"""The other half of check 1 — the branch that cannot use `db_set`.

		The sibling test forces `source = "Image"` so the UPDATE branch runs. That
		branch is guarded. The INSERT branch was not: `.insert()` lets
		`validate_disabled_and_default` set `is_default = 1`, and `on_update`'s
		`set_as_default()` then writes `set_default("letter_head", …)` and
		`set_default("default_letter_head_content", …)` — DefaultValue rows that a
		following `db_set("is_default", 0)` does not touch.

		So this deletes the record INSIDE the no-default window and lets
		provisioning recreate it. Same class-scoped rollback caveat as the sibling:
		everything is restored in a `finally`.
		"""
		module = katc_letterhead()
		defaults = frappe.get_all("Letter Head", filters={"is_default": 1}, pluck="name")
		try:
			for name in defaults:
				frappe.db.set_value("Letter Head", name, "is_default", 0, update_modified=False)
			frappe.delete_doc(
				"Letter Head", module.KATC_LETTER_HEAD, force=True, ignore_permissions=True
			)
			self.assertFalse(
				frappe.db.exists("Letter Head", module.KATC_LETTER_HEAD),
				"the INSERT branch is only exercised when the record is gone",
			)

			module.setup_katc_letterhead()

			self.assertTrue(
				frappe.db.exists("Letter Head", module.KATC_LETTER_HEAD),
				"provisioning must recreate the record",
			)
			self.assertNotEqual(
				frappe.db.get_value(
					"DefaultValue", {"parent": "__default", "defkey": "letter_head"}, "defvalue"
				),
				module.KATC_LETTER_HEAD,
				f"{module.KATC_LETTER_HEAD} became the site-wide default Letter Head",
			)
			self.assertFalse(
				frappe.db.get_value(
					"DefaultValue",
					{"parent": "__default", "defkey": "default_letter_head_content"},
					"defvalue",
				),
				"set_as_default's default_letter_head_content row survived",
			)
			self.assertFalse(
				frappe.db.get_value("Letter Head", module.KATC_LETTER_HEAD, "is_default"),
				"is_default was taken on a site with no other default",
			)
			self.assertEqual(
				frappe.db.get_value("Letter Head", module.KATC_LETTER_HEAD, "source"),
				"HTML",
				"before_insert forces Image and the insert branch must repair it",
			)
		finally:
			for name in defaults:
				frappe.db.set_value("Letter Head", name, "is_default", 1, update_modified=False)

	def test_the_content_carries_the_artefact_facts(self):
		# check 2
		content = frappe.db.get_value(
			"Letter Head", katc_letterhead().KATC_LETTER_HEAD, "content"
		) or ""
		for fact in (ARTEFACT_VAT, ARTEFACT_CR, ARTEFACT_COMPANY_AR, LOGO_URL):
			with self.subTest(fact=fact):
				self.assertIn(fact, content)

	def test_the_content_is_a_fragment_not_a_page(self):
		"""check 3 — a Letter Head is injected INTO a print page.

		`@page`, `html {width:210mm}` and friends belong to a standalone document
		and would wreck every format that carries them.
		"""
		content = (
			frappe.db.get_value("Letter Head", katc_letterhead().KATC_LETTER_HEAD, "content") or ""
		).lower()
		for banned in ("<!doctype", "<html", "<body", "@page", ".content-area"):
			with self.subTest(banned=banned):
				self.assertNotIn(banned, content)

	def test_the_content_uses_a_table_not_flexbox(self):
		"""check 4 — wkhtmltopdf 0.12.x runs an old WebKit; flexbox is unreliable."""
		content = (
			frappe.db.get_value("Letter Head", katc_letterhead().KATC_LETTER_HEAD, "content") or ""
		).lower()
		self.assertNotIn("display:flex", content.replace(" ", ""))
		self.assertIn("<table", content)
		self.assertIn("<tbody", content, "emit <tbody> by hand or every migrate rewrites it")

	def test_provisioning_is_idempotent(self):
		"""check 5 — gotcha 26: frappe normalises HTML on save and adds <tbody>.

		If the comparison never holds, every migrate rewrites the record and floods
		the Version table.
		"""
		module = katc_letterhead()
		first = module.setup_katc_letterhead()
		second = module.setup_katc_letterhead()
		self.assertEqual(second["created"], 0)
		self.assertEqual(second["updated"], 0)
		self.assertEqual(
			second["unchanged"], first["created"] + first["updated"] + first["unchanged"]
		)

	def test_provisioning_writes_no_other_letter_head(self):
		"""Shared state: the incumbent and the per-branch heads must not be touched."""
		before = dict(frappe.get_all("Letter Head", fields=["name", "modified"], as_list=True))
		katc_letterhead().setup_katc_letterhead()
		after = dict(frappe.get_all("Letter Head", fields=["name", "modified"], as_list=True))
		for name, modified in before.items():
			if name == EXPECTED_LETTER_HEAD:
				continue
			with self.subTest(letter_head=name):
				self.assertEqual(after.get(name), modified, f"{name} was rewritten")

	def test_the_incumbent_letterhead_is_untouched(self):
		# check 6
		if not frappe.db.exists("Letter Head", INCUMBENT_LETTER_HEAD):
			self.skipTest(f"{INCUMBENT_LETTER_HEAD} is not on this site")
		row = frappe.db.get_value(
			"Letter Head",
			INCUMBENT_LETTER_HEAD,
			["source", "is_default", "image"],
			as_dict=True,
		)
		self.assertEqual(row.source, "Image")
		self.assertTrue(row.is_default, "the incumbent lost its default flag")
		self.assertEqual(row.image, INCUMBENT_IMAGE)

	def test_the_company_default_is_left_alone(self):
		# check 7
		default = frappe.db.get_value("Company", {}, "default_letter_head")
		if not default:
			self.skipTest("no company default letterhead")
		self.assertFalse(
			default.startswith("KATC"),
			"the KATC letterhead was made the company default",
		)

	def test_the_branch_letterheads_still_exist(self):
		# check 8
		branches = frappe.get_all("Branch", pluck="name")
		if not branches:
			self.skipTest("no Branch on this site")
		for branch in branches:
			with self.subTest(branch=branch):
				name = letterhead.letter_head_name(branch)
				self.assertTrue(frappe.db.exists("Letter Head", name))
				self.assertEqual(frappe.db.get_value("Letter Head", name, "source"), "HTML")

	def test_the_logo_asset_ships_and_is_small(self):
		"""check 9 — the client supplied a ~320 KB base64 data URI (Q1: rejected).

		Letter Head content is re-rendered through jinja on EVERY print and is
		scrubbed by `scrub_urls`; an /assets/ URL is what the incumbent image
		letterhead already does successfully on this site.
		"""
		path = frappe.get_app_path("yht_custom", "public", "images", "katc_logo.jpg")
		self.assertTrue(os.path.exists(path), f"{path} does not exist")
		with open(path, "rb") as fh:
			head = fh.read(3)
		self.assertEqual(head, b"\xff\xd8\xff", "not a JPEG")
		size = os.path.getsize(path)
		self.assertLessEqual(size, LOGO_MAX_BYTES, f"logo is {size} bytes, cap is {LOGO_MAX_BYTES}")

	def test_the_provisioning_step_is_wired_into_after_migrate(self):
		"""It must run on every deploy, inside the per-step try/except."""
		self.assertIn("setup_katc_letterhead", setup.PROVISIONING_STEPS)
		steps = list(setup.PROVISIONING_STEPS)
		self.assertGreater(
			steps.index("setup_katc_letterhead"),
			steps.index("setup_branch_letterheads"),
			"KATC provisioning must run after the branch letterheads",
		)
		resolved = getattr(setup, "setup_katc_letterhead", None) or setup._imported(
			"setup_katc_letterhead"
		)
		self.assertTrue(callable(resolved))


# =============================================================== all ten


class TestKatcFormatsInstalled(FrappeTestCase):
	"""Checks 10-17."""

	def test_all_ten_install_correctly(self):
		# check 10
		for print_format, doctype in FORMATS:
			with self.subTest(print_format=print_format):
				row = frappe.db.get_value(
					"Print Format",
					print_format,
					["doc_type", "disabled", "print_format_type", "standard", "module"],
					as_dict=True,
				)
				self.assertTrue(row, f"{print_format} is not installed")
				self.assertEqual(row.doc_type, doctype)
				self.assertFalse(row.disabled)
				self.assertEqual(row.print_format_type, "Jinja")
				self.assertEqual(row.standard, "Yes")
				self.assertEqual(row.module, "Yht Custom")

	def test_every_format_renders_a_real_document(self):
		# check 11
		for print_format, doctype in FORMATS:
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			with self.subTest(print_format=print_format):
				html = render(doctype, name, print_format)
				self.assertGreater(len(html), 2000, f"{print_format} rendered almost nothing")

	def test_the_bilingual_formats_print_arabic(self):
		# check 12
		for print_format, doctype in FORMATS:
			if print_format not in ARABIC_BODY_FORMATS:
				continue
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			with self.subTest(print_format=print_format):
				html = render(doctype, name, print_format, no_letterhead=1)
				self.assertTrue(ARABIC.search(html), f"{print_format} printed no Arabic")

	def test_the_english_layouts_carry_their_titles(self):
		"""check 12 (second half) — these two are English-body by design."""
		for print_format, title in ENGLISH_BODY_TITLES.items():
			doctype = dict(FORMATS)[print_format]
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			with self.subTest(print_format=print_format):
				self.assertIn(title, render(doctype, name, print_format, no_letterhead=1))

	def test_no_format_reaches_for_a_sandboxed_default(self):
		"""check 13 — gotcha 24. `frappe.defaults` is a function in the sandbox."""
		for print_format, _doctype in FORMATS:
			with self.subTest(print_format=print_format):
				html = format_source(print_format)
				self.assertNotIn("frappe.defaults", html)

	def test_every_format_emits_exactly_one_footer_html(self):
		"""check 14 — `prepare_header_footer` extracts it for wkhtmltopdf's
		`--footer-html`, which is the only way `<span class="page">` resolves."""
		for print_format, doctype in FORMATS:
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			with self.subTest(print_format=print_format):
				html = render(doctype, name, print_format, no_letterhead=1)
				self.assertEqual(
					len(re.findall(r'id\s*=\s*["\']footer-html["\']', html)),
					1,
					f"{print_format} must emit exactly one id=footer-html",
				)

	def test_a_document_with_no_items_renders(self):
		# check 15
		for print_format, doctype in FORMATS:
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			doc = frappe.get_doc(doctype, name)
			doc.items = []
			with self.subTest(print_format=print_format):
				html = frappe.get_print(doctype, name, print_format=print_format, doc=doc, no_letterhead=1)
				self.assertTrue(html)

	def test_a_document_with_no_customer_address_renders(self):
		# check 16
		for print_format, doctype in FORMATS:
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			doc = frappe.get_doc(doctype, name)
			doc.customer_address = None
			doc.address_display = ""
			with self.subTest(print_format=print_format):
				html = frappe.get_print(doctype, name, print_format=print_format, doc=doc, no_letterhead=1)
				self.assertTrue(html)

	def test_a_dangling_letter_head_does_not_raise(self):
		"""check 17 — 1,266 documents point at a Letter Head that does not exist."""
		self.assertFalse(
			frappe.db.exists("Letter Head", DANGLING_LETTER_HEAD),
			"the dangling letterhead was created — this test no longer tests anything",
		)
		for print_format, doctype in FORMATS:
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			doc = frappe.get_doc(doctype, name)
			doc.letter_head = DANGLING_LETTER_HEAD
			with self.subTest(print_format=print_format):
				html = frappe.get_print(doctype, name, print_format=print_format, doc=doc)
				self.assertTrue(html)


# ================================================= the no_letterhead pair


class TestNoLetterheadToggle(FrappeTestCase):
	"""Checks 18-21. Delivery Note and Sales Invoice: ONE format, two outputs."""

	def test_with_letterhead_carries_the_logo(self):
		# check 18
		for print_format, doctype in TOGGLED:
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			with self.subTest(print_format=print_format):
				html = render(
					doctype, name, print_format, letterhead=EXPECTED_LETTER_HEAD, no_letterhead=0
				)
				self.assertIn("katc_logo.jpg", html)

	def test_without_letterhead_drops_the_logo(self):
		# check 19
		for print_format, doctype in TOGGLED:
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			with self.subTest(print_format=print_format):
				html = render(doctype, name, print_format, no_letterhead=1)
				self.assertNotIn("katc_logo.jpg", html)

	maxDiff = None

	def test_the_two_bodies_are_identical(self):
		"""check 20 — THE decision test.

		The client's two supplied PDFs extract to byte-identical text and differ
		only by one embedded 43,812-byte JPEG. That is why one format is enough for
		these two doctypes. Strip the outer `<thead>` from both renders and the
		remainders must match exactly.
		"""
		for print_format, doctype in TOGGLED:
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			with self.subTest(print_format=print_format):
				with_lh = render(
					doctype, name, print_format, letterhead=EXPECTED_LETTER_HEAD, no_letterhead=0
				)
				without = render(doctype, name, print_format, no_letterhead=1)
				with_lh, without = format_body(with_lh), format_body(without)
				self.assertNotEqual(squash(with_lh), squash(without), "the toggle did nothing")
				self.assertEqual(
					squash(strip_first_thead(with_lh)),
					squash(strip_first_thead(without)),
					f"{print_format}: the two bodies differ by more than the header",
				)

	def test_no_argument_does_not_smuggle_in_the_incumbent_image(self):
		"""check 21 — `get_letter_head` prefers `doc.letter_head` over the default.

		On this site documents carry `letter_head = "KATHOOM ALKHOBAR"`. A format
		that renders whatever `letter_head` it is handed will print the incumbent
		image on a KATC layout — the failure mode most likely to reach the client.
		The KATC formats must render the KATC letterhead or nothing.
		"""
		for print_format, doctype in TOGGLED:
			name = frappe.db.get_value(
				doctype, {"docstatus": 1, "letter_head": INCUMBENT_LETTER_HEAD}, "name"
			) or artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			doc = frappe.get_doc(doctype, name)
			doc.letter_head = INCUMBENT_LETTER_HEAD
			with self.subTest(print_format=print_format):
				html = frappe.get_print(doctype, name, print_format=print_format, doc=doc)
				self.assertNotIn("KhobarHeading1.jpg", html)


# ========================================== the two-format doctypes


class TestTwoFormatDoctypes(FrappeTestCase):
	"""Checks 22-26. Sales Order and Quotation get genuinely different bodies."""

	maxDiff = None

	def test_the_sales_order_pair_are_different_documents(self):
		# check 22
		name = artefact_or_any("Sales Order")
		if not name:
			self.skipTest("no submitted Sales Order")
		proforma = render("Sales Order", name, "KATC Proforma Invoice", no_letterhead=1)
		plain = render("Sales Order", name, "KATC Sales Order No LH", no_letterhead=1)

		self.assertIn("PROFORMA INVOICE", proforma)
		self.assertNotIn("PROFORMA INVOICE", plain)
		self.assertIn("SALES ORDER", plain)
		self.assertNotIn("SALES ORDER", proforma)

	def test_the_quotation_pair_are_different_documents(self):
		# check 23
		name = artefact_or_any("Quotation")
		if not name:
			self.skipTest("no submitted Quotation")
		one = render("Quotation", name, "KATC Quotation", no_letterhead=1)
		two = render("Quotation", name, "KATC Quotation No LH", no_letterhead=1)
		self.assertNotEqual(squash(strip_first_thead(one)), squash(strip_first_thead(two)))
		# `quote Print 2` is the bilingual one; `quote Print 1` is not.
		self.assertIn("QUOTATION", two)
		self.assertTrue(ARABIC.search(two), "the No LH quotation is the bilingual layout")

	def test_the_without_lh_button_never_asks_for_a_letterhead(self):
		"""check 24, restated — the guarantee moved from the format to the button.

		🔴 It used to be structural: the No-LH formats simply had no letterhead markup,
		so handing them one changed nothing. That is also why there was no
		with-letterhead plain Sales Order at all — its spacer was unconditional. The
		templates are now shared and render `{{ letter_head }}` when one is passed, so
		the guarantee is the BUTTON's: the Without-LH path must send `no_letterhead=1`
		and must NOT send a `letterhead=`. Asserting the old structural property would
		now assert the bug back in.
		"""
		specs = button_specs(js_source())
		without = [s for s in specs if s["no_letterhead"] == "1"]
		self.assertTrue(without, "no Without-LH buttons found")
		for spec in without:
			with self.subTest(print_format=spec["format"]):
				self.assertFalse(
					spec.get("letterhead"),
					f"the Without LH button for {spec['format']} passes a letterhead",
				)

	def test_the_no_lh_formats_render_no_letterhead_when_none_is_passed(self):
		"""And the way the button actually calls them, nothing leaks in."""
		for print_format, doctype in NO_LH_FORMATS:
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			with self.subTest(print_format=print_format):
				html = render(doctype, name, print_format, no_letterhead=1)
				self.assertNotIn("katc_logo.jpg", html)
				self.assertNotIn("KhobarHeading1.jpg", html)

	def test_the_no_lh_formats_emit_the_measured_spacer(self):
		"""check 25 — measured, not assumed, and owned in ONE place.

		The four artefact pairs' first-glyph y (`pdftotext -bbox`, page 1):
		`DN Print 1` 136.02 / `DN print 2` 160.02 · `Invoice Print 1` 148.40 /
		`Invoice Print 2` 172.40 · `SO Print 1` 134.52 / `SO Print 2` 149.52 ·
		`quote Print 1` 138.22 / `quote Print 2` 149.52.

		`katc_letterhead.NO_LH_SPACER_PT` is the height that puts the rendered
		body at or below every one of those without-letterhead positions, which is
		what makes the print clear the pre-printed stationery. The formats reach it
		through `yht_katc_spacer_pt()`, so this asserts the ONE constant rather
		than a literal that can drift away from it.
		"""
		# 🔴 PIN THE MEASUREMENT. The regex below is built FROM the constant, so it
		# matches whatever the constant says — set it to 7 and this check stays
		# green while every no-LH print overlaps the pre-printed stationery. The
		# value comes from the twelve-render table in `.pipeline/changes.md`
		# against the bbox positions quoted above. Re-measure before changing it.
		self.assertEqual(
			katc_letterhead().NO_LH_SPACER_PT,
			194,
			"re-measure against the artefacts before changing NO_LH_SPACER_PT",
		)
		spacer = re.compile(rf"height\s*:\s*{katc_letterhead().NO_LH_SPACER_PT}\s*pt", re.I)
		for print_format, doctype in NO_LH_FORMATS:
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			with self.subTest(print_format=print_format):
				self.assertTrue(
					spacer.search(render(doctype, name, print_format, no_letterhead=1)),
					f"{print_format} does not emit NO_LH_SPACER_PT as its spacer height",
				)

		# and the toggled pair grows one only on the no_letterhead path
		for print_format, doctype in TOGGLED:
			name = artefact_or_any(doctype)
			if not name:
				continue
			with self.subTest(print_format=print_format, path="no_letterhead=1"):
				self.assertTrue(
					spacer.search(render(doctype, name, print_format, no_letterhead=1)),
					f"{print_format} must spacer the body down when the header is absent",
				)

	def test_the_arabic_quotation_differs_by_exactly_three_things(self):
		"""check 26 — the Arabic column, the bank block, the pinned widths. No more.

		It used to assert ONE difference, and that assertion held a real fidelity gap
		in place: `quote print 2 with arabic.pdf` carries Print 2's VAT # / BANK DETAILS
		block on its last page, and Print 1 — the base this format is built on, which the
		artefact mapping confirmed is the correct base — does not. Adding the block to
		the Arabic format alone failed this test; adding it to both would have put a bank
		block on Print 1's output, which the artefact does not have. So it hangs off its
		own `katc_show_bank` flag and this test knows about both differences.
		"""
		name = artefact_or_any("Quotation")
		if not name:
			self.skipTest("no submitted Quotation")
		plain = format_body(render("Quotation", name, "KATC Quotation", no_letterhead=1))
		arabic = format_body(render("Quotation", name, "KATC Quotation Arabic", no_letterhead=1))

		self.assertNotEqual(squash(plain), squash(arabic), "the Arabic column is missing")
		self.assertIn("BANK DETAILS", arabic, "the artefact's VAT / bank block is missing")
		self.assertNotIn("BANK DETAILS", plain, "Print 1 does not carry a bank block")
		self.assertEqual(
			squash(strip_column_widths(strip_bank_block(strip_first_thead(plain)))),
			squash(
				strip_column_widths(
					strip_bank_block(strip_arabic_column(strip_first_thead(arabic)))
				)
			),
			"KATC Quotation Arabic diverges beyond the Arabic column, the bank block "
			"and the pinned column widths",
		)


# ============================================================= yht_item_ar


class TestItemArabicName(FrappeTestCase):
	"""Checks 27-32. Step 4: child row first, per parent doctype."""

	def test_a_quotation_row_is_read_off_the_row(self):
		"""check 27 — the row is already loaded, so this must cost NO query."""
		yht_item_ar = helper("yht_item_ar")
		row = frappe._dict(
			doctype="Quotation Item",
			item_code="does-not-exist-anywhere",
			custom_item_name_in_arabic="أنبوب حديد",
		)
		calls = []
		original = frappe.db.get_value

		def spy(doctype, *args, **kwargs):
			calls.append(doctype)
			return original(doctype, *args, **kwargs)

		frappe.db.get_value = spy
		try:
			self.assertEqual(yht_item_ar(row), "أنبوب حديد")
		finally:
			frappe.db.get_value = original
		self.assertNotIn("Item", calls, "the row was already loaded — no Item query is allowed")

	def test_a_sales_invoice_row_prefers_the_newer_fieldname(self):
		"""check 28 — 11,507 rows on `custom_item_arabic_name`, 8,055 on the older."""
		yht_item_ar = helper("yht_item_ar")
		row = frappe._dict(
			doctype="Sales Invoice Item",
			item_code="does-not-exist-anywhere",
			custom_item_arabic_name="الجديد",
			item_arabic_name="القديم",
		)
		self.assertEqual(yht_item_ar(row), "الجديد")

		older = frappe._dict(
			doctype="Sales Invoice Item",
			item_code="does-not-exist-anywhere",
			item_arabic_name="القديم",
		)
		self.assertEqual(yht_item_ar(older), "القديم")

	def test_a_row_with_no_arabic_falls_back_to_the_item(self):
		# check 29
		yht_item_ar = helper("yht_item_ar")
		item_code = frappe.db.get_value("Item", {}, "name")
		if not item_code:
			self.skipTest("no Item on this site")
		row = frappe._dict(doctype="Quotation Item", item_code=item_code)
		result = yht_item_ar(row)  # must not raise
		self.assertIsInstance(result, str)

	def test_a_bare_item_code_still_works(self):
		"""check 30 — the six existing `YHT *` formats call `yht_item_ar(row.item_code)`.

		Their behaviour must not change in this commit.
		"""
		yht_item_ar = helper("yht_item_ar")
		item_code = frappe.db.get_value("Item", {}, "name")
		if not item_code:
			self.skipTest("no Item on this site")
		self.assertIsInstance(yht_item_ar(item_code), str)
		self.assertEqual(yht_item_ar(""), "")
		self.assertEqual(yht_item_ar(None), "")

	def test_the_item_fallback_is_memoised(self):
		"""check 31 — a per-row query on a 50-line document is an N+1, a blocker here."""
		yht_item_ar = helper("yht_item_ar")
		codes = frappe.get_all("Item", limit=4, pluck="name")
		if len(codes) < 2:
			self.skipTest("not enough Items to measure memoisation")

		reset = getattr(print_helpers, "clear_item_ar_cache", None)
		if callable(reset):
			reset()

		item_reads = []
		original = frappe.db.get_value

		def spy(doctype, *args, **kwargs):
			if doctype == "Item":
				item_reads.append(args[0] if args else None)
			return original(doctype, *args, **kwargs)

		frappe.db.get_value = spy
		try:
			for _ in range(5):
				for code in codes:
					yht_item_ar(frappe._dict(doctype="Quotation Item", item_code=code))
		finally:
			frappe.db.get_value = original

		self.assertLessEqual(
			len(item_reads),
			len(codes),
			f"{len(item_reads)} Item reads for {len(codes)} distinct codes — not memoised",
		)

	def test_an_unknown_item_returns_empty_string_not_none(self):
		# check 32
		yht_item_ar = helper("yht_item_ar")
		self.assertEqual(yht_item_ar("no-such-item-code-at-all"), "")
		self.assertEqual(
			yht_item_ar(frappe._dict(doctype="Quotation Item", item_code="no-such-item-code-at-all")),
			"",
		)

	def test_the_docstring_names_the_orphaned_column(self):
		"""Step 4: `Item.custom_item_name_in_arabic` has a column and 3,857 rows but
		NO DocField (gotcha 22). That decision must not hide in a comment."""
		doc = (helper("yht_item_ar").__doc__ or "").lower()
		self.assertIn("orphan", doc, "the orphaned Item column is undocumented")


# ================================================================= ZATCA QR


class TestZatcaQr(FrappeTestCase):
	"""Checks 33-34."""

	def test_a_missing_qr_degrades_to_an_empty_string(self):
		"""check 33 — `get_zatca_phase_1_qr_for_invoice` returns None when there is
		no `ZATCA Phase 1 Business Settings` row for the company, or it is Disabled.
		The invoice must still print before ZATCA onboarding."""
		yht_zatca_qr = helper("yht_zatca_qr")
		doc = frappe._dict(doctype="Sales Invoice", name="no-such-invoice", company="KATC")
		result = yht_zatca_qr(doc)
		self.assertIsInstance(result, str)
		self.assertEqual(result, "")

	def test_the_invoice_renders_without_a_qr_image(self):
		# check 33 (rendered half)
		name = artefact_or_any("Sales Invoice")
		if not name:
			self.skipTest("no submitted Sales Invoice")
		original = getattr(print_helpers, "yht_zatca_qr", None)
		if original is None:
			self.fail("print_helpers.yht_zatca_qr does not exist")
		print_helpers.yht_zatca_qr = lambda doc: ""
		try:
			html = render("Sales Invoice", name, "KATC Tax Invoice", no_letterhead=1)
		finally:
			print_helpers.yht_zatca_qr = original
		self.assertNotIn("data:image/png;base64,", html)
		self.assertGreater(len(html), 2000)

	def test_a_real_qr_is_rendered_inline(self):
		# check 34
		yht_zatca_qr = helper("yht_zatca_qr")
		name = artefact_or_any("Sales Invoice")
		if not name:
			self.skipTest("no submitted Sales Invoice")
		doc = frappe.get_doc("Sales Invoice", name)
		if not yht_zatca_qr(doc):
			self.skipTest("no ZATCA Phase 1 settings on this site — check 34 is unmeasurable")
		html = render("Sales Invoice", name, "KATC Tax Invoice", no_letterhead=1)
		self.assertIn("data:image/png;base64,", html)


	def test_a_stored_qr_is_preferred_over_a_recomputed_one(self):
		"""check 34a — the migrated invoices carry the QR they were CLEARED with under
		Phase 2, in `ksa_einv_qr`. Recomputing a Phase-1 QR for one of those would
		print a different, weaker code than the buyer was handed and than ZATCA holds."""
		name = frappe.db.get_value(
			"Sales Invoice", {"docstatus": 1, "ksa_einv_qr": ("!=", "")}, "name"
		)
		if not name:
			self.skipTest("no invoice carries a stored ZATCA QR on this site")
		doc = frappe.get_doc("Sales Invoice", name)
		expected = print_helpers._stored_zatca_qr_b64(doc.get("ksa_einv_qr"))
		self.assertTrue(expected, "the stored QR file should be readable")
		self.assertEqual(helper("yht_zatca_qr")(doc), expected)

	def test_the_stored_qr_path_cannot_escape_the_site(self):
		"""check 34b — `ksa_einv_qr` is an Attach field, so its value is DATA. A `../`
		walk must not turn a customer-facing invoice into a file-read primitive."""
		for hostile in (
			"/private/files/../../../../etc/passwd",
			"/files/../../site_config.json",
			"/files/../private/files/../../../etc/hostname",
			"http://example.invalid/qr.png",
			"/etc/passwd",
			"",
			None,
		):
			self.assertEqual(print_helpers._stored_zatca_qr_b64(hostile), "", hostile)

	def test_an_invoice_with_no_stored_qr_still_prints(self):
		"""check 34c — 705 migrated invoices predate the client's ZATCA rollout and
		carry no QR at all. They must print, without a broken <img>."""
		name = frappe.db.get_value(
			"Sales Invoice", {"docstatus": 1, "ksa_einv_qr": ("in", ("", None))}, "name"
		)
		if not name:
			self.skipTest("every invoice on this site carries a QR")
		html = render("Sales Invoice", name, "KATC Tax Invoice", no_letterhead=1)
		self.assertGreater(len(html), 2000)
		self.assertNotIn('src="data:image/png;base64,"', html)


# ====================================== bank block and Bank Account permission


class TestBankBlockAndPermission(FrappeTestCase):
	"""🔴 Checks 35-39. The constraint that already broke the payment flow once."""

	BRANCH_TEST_USER = "yht-katc-print@example.com"

	def setUp(self):
		# gotcha 12: fixtures in setUpClass vanish after the first test.
		self.company = frappe.db.get_value("Company", {}, "name")
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	def _branch_user(self):
		if not frappe.db.exists("Role", "Branch User"):
			self.skipTest("Branch User role not provisioned")
		if not frappe.db.exists("User", self.BRANCH_TEST_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": self.BRANCH_TEST_USER,
					"first_name": "KATC Print",
					"user_type": "System User",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", self.BRANCH_TEST_USER)
		user.user_type = "System User"
		if "Branch User" not in {r.role for r in user.roles}:
			user.append("roles", {"role": "Branch User"})
		user.flags.ignore_permissions = True
		user.save(ignore_permissions=True)
		# gotcha 19: a role inserted moments ago is not in the cached permission set.
		frappe.clear_cache(user=self.BRANCH_TEST_USER)
		return self.BRANCH_TEST_USER

	def test_a_branch_user_can_render_the_bank_block_formats(self):
		"""🔴 check 35 — the regression test.

		`erpnext`'s Bank Account controller calls `frappe.has_permission(...,
		throw=True)`, which NO `ignore_permissions` flag suppresses, and this
		project denies branch users `read` on Bank Account on purpose. A
		`frappe.get_doc("Bank Account", …)` in a print helper makes both of these
		formats unprintable for every branch user, with a bare PermissionError and
		no message.
		"""
		user = self._branch_user()
		yht_bank_details = helper("yht_bank_details")

		frappe.set_user(user)
		try:
			if frappe.has_permission("Bank Account", ptype="read"):
				# Not a failure of THIS change, but it makes check 35 unmeasurable and it
				# is itself the exposure setup.py denies on purpose. Say so loudly.
				self.skipTest(
					"REPORT: the Branch User role currently HAS read on Bank Account on this "
					"site — check 35 cannot prove anything until that is taken away, and the "
					"account number and IBAN of every company account are visible in the desk UI"
				)
			details = yht_bank_details()  # must not raise PermissionError
			self.assertIsInstance(details, dict)

			for print_format, doctype in (
				("KATC Proforma Invoice", "Sales Order"),
				("KATC Quotation No LH", "Quotation"),
			):
				name = artefact_or_any(doctype)
				if not name:
					continue
				with self.subTest(print_format=print_format):
					html = render(doctype, name, print_format, no_letterhead=1)
					self.assertGreater(len(html), 2000)
		finally:
			frappe.set_user("Administrator")

	def test_print_helpers_never_opens_a_bank_account_document(self):
		"""check 36 — asserted against the SOURCE so a future edit cannot
		reintroduce it silently."""
		import inspect

		source = inspect.getsource(print_helpers)
		flat = re.sub(r"\s+", " ", source)
		for pattern in (
			r"get_doc\(\s*[\"']Bank Account[\"']",
			r"get_cached_doc\(\s*[\"']Bank Account[\"']",
		):
			with self.subTest(pattern=pattern):
				self.assertIsNone(
					re.search(pattern, flat),
					"Bank Account must be read with frappe.db, never through the controller",
				)

	def test_branch_users_still_have_no_bank_account_permission(self):
		# check 37
		parents = {p["parent"] for p in setup.BRANCH_USER_PERMISSIONS}
		self.assertNotIn(
			"Bank Account",
			parents,
			"granting read on Bank Account exposes every company account's IBAN in the desk UI",
		)

	def test_a_missing_record_degrades_to_nothing(self):
		"""check 38 — never a half-populated `IBAN :` line."""
		yht_bank_details = helper("yht_bank_details")
		original_get_value = frappe.db.get_value
		original_cached = frappe.db.get_cached_value if hasattr(frappe.db, "get_cached_value") else None

		def blind(doctype, *args, **kwargs):
			if doctype == "Bank Account":
				return None
			return original_get_value(doctype, *args, **kwargs)

		frappe.db.get_value = blind
		cached_original = getattr(frappe, "get_cached_value", None)
		if cached_original:
			frappe.get_cached_value = lambda dt, *a, **k: (
				None if dt == "Bank Account" else cached_original(dt, *a, **k)
			)
		try:
			details = yht_bank_details()
		finally:
			frappe.db.get_value = original_get_value
			if cached_original:
				frappe.get_cached_value = cached_original
			if original_cached is not None:
				frappe.db.get_cached_value = original_cached

		self.assertEqual(set(details), {"bank", "iban", "account_no"})
		self.assertEqual(
			[v for v in details.values() if v], [], "a partially populated bank block was returned"
		)

	def test_the_block_follows_the_live_record(self):
		"""check 39 — the bank must not be a literal in the template.

		The site's DEFAULT Bank Account is `Saudi National Bank - KATC`, but the
		artefacts print AL RAJHI. Resolving by `is_default` would print the wrong
		bank on a customer-facing document (Step 10, constraint 2).
		"""
		yht_bank_details = helper("yht_bank_details")
		details = yht_bank_details()
		if not details.get("iban"):
			self.skipTest("no matching Bank Account on this site — OQ-1, surfaced at check 58")

		account = frappe.db.get_value("Bank Account", {"iban": details["iban"]}, "name")
		self.assertTrue(account, "yht_bank_details returned an IBAN with no Bank Account behind it")

		frappe.db.set_value("Bank Account", account, "bank", "TEST BANK OF NOWHERE")
		frappe.clear_cache()
		self.assertEqual(yht_bank_details()["bank"], "TEST BANK OF NOWHERE")

		name = artefact_or_any("Sales Order")
		if name:
			html = render("Sales Order", name, "KATC Proforma Invoice", no_letterhead=1)
			self.assertIn("TEST BANK OF NOWHERE", html)
		# FrappeTestCase rolls this back.


# ============================================================== other helpers


class TestOtherHelpers(FrappeTestCase):
	"""Checks 40-43."""

	def test_national_address_returns_seven_keys(self):
		# check 40
		yht_national_address = helper("yht_national_address")
		name = artefact_or_any("Sales Invoice")
		if not name:
			self.skipTest("no submitted Sales Invoice")
		doc = frappe.get_doc("Sales Invoice", name)
		result = yht_national_address(doc, "customer_address")
		self.assertEqual(set(result), NATIONAL_ADDRESS_KEYS)
		for key, value in result.items():
			with self.subTest(key=key):
				self.assertIsInstance(value, str, "every key defaults to '', never None")

	def test_national_address_degrades_when_there_is_no_address(self):
		# check 40 (second half)
		yht_national_address = helper("yht_national_address")
		doc = frappe._dict(doctype="Sales Invoice", customer_address=None)
		result = yht_national_address(doc, "customer_address")
		self.assertEqual(set(result), NATIONAL_ADDRESS_KEYS)
		self.assertEqual([v for v in result.values() if v], [])

	def test_national_address_is_read_once_per_document(self):
		"""N+1 discipline: one Address read per document, not per row."""
		yht_national_address = helper("yht_national_address")
		name = artefact_or_any("Sales Invoice")
		if not name:
			self.skipTest("no submitted Sales Invoice")
		doc = frappe.get_doc("Sales Invoice", name)
		if not doc.get("customer_address"):
			self.skipTest("the sample invoice has no customer_address")

		reads = []
		original = frappe.db.get_value

		def spy(doctype, *args, **kwargs):
			if doctype == "Address":
				reads.append(doctype)
			return original(doctype, *args, **kwargs)

		frappe.db.get_value = spy
		try:
			yht_national_address(doc, "customer_address")
		finally:
			frappe.db.get_value = original
		self.assertLessEqual(len(reads), 1, "the address must be read once, not per field")

	def test_sales_person_falls_back_to_the_owner(self):
		# check 41
		yht_sales_person = helper("yht_sales_person")
		name = artefact_or_any("Sales Order")
		if not name:
			self.skipTest("no submitted Sales Order")
		doc = frappe.get_doc("Sales Order", name)
		doc.sales_team = []
		expected = frappe.db.get_value("User", doc.owner, "full_name") or ""
		self.assertEqual(yht_sales_person(doc), expected)

	def test_sales_person_prefers_the_sales_team(self):
		yht_sales_person = helper("yht_sales_person")
		row = frappe.db.get_value(
			"Sales Team", {"parenttype": "Sales Order"}, ["parent", "sales_person"], as_dict=True
		)
		if not row:
			self.skipTest("no Sales Order carries a Sales Team row")
		doc = frappe.get_doc("Sales Order", row.parent)
		self.assertEqual(yht_sales_person(doc), row.sales_person)

	def test_creator_contact_returns_name_and_mobile(self):
		"""check 42 — Q3: this REPLACES the incumbent's `Created By Name` /
		`Creator Mobile No` Custom Fields. We add no fields."""
		yht_creator_contact = helper("yht_creator_contact")
		name = artefact_or_any("Quotation")
		if not name:
			self.skipTest("no submitted Quotation")
		doc = frappe.get_doc("Quotation", name)
		result = yht_creator_contact(doc)
		self.assertEqual(set(result), {"name", "mobile"})
		for key, value in result.items():
			with self.subTest(key=key):
				self.assertIsInstance(value, str)

	def test_creator_contact_degrades_for_an_unknown_user(self):
		yht_creator_contact = helper("yht_creator_contact")
		result = yht_creator_contact(frappe._dict(doctype="Quotation", owner="nobody@example.com"))
		self.assertEqual(result, {"name": "", "mobile": ""})

	def test_no_new_custom_fields_were_created(self):
		"""Q3 — the whole point of deriving from `doc.owner`."""
		for fieldname in (
			"Quotation-custom_created_by_name",
			"Quotation-custom_creator_mobile_no",
			"Sales Invoice-custom_buyer_cr_number",
			"Sales Order-custom_created_by_name",
		):
			with self.subTest(field=fieldname):
				self.assertFalse(
					frappe.db.exists("Custom Field", fieldname),
					f"{fieldname} was created — Q3 decided no new Custom Fields",
				)

	def test_the_letterhead_name_helper_is_the_single_source_of_truth(self):
		# check 43
		self.assertEqual(helper("yht_katc_lh")(), katc_letterhead().KATC_LETTER_HEAD)


class TestCompanyVatLine(FrappeTestCase):
	"""Spec Step 10's `VAT #` line — the seller VAT above the bank block."""

	def test_company_vat_reads_the_company_tax_id(self):
		yht_company_vat = helper("yht_company_vat")
		name = artefact_or_any("Sales Order")
		if not name:
			self.skipTest("no submitted Sales Order")
		doc = frappe.get_doc("Sales Order", name)
		expected = (frappe.db.get_value("Company", doc.company, "tax_id") or "").strip()
		self.assertEqual(yht_company_vat(doc), expected)

	def test_company_vat_degrades_instead_of_raising(self):
		"""A document with no company must print no line, not a traceback."""
		yht_company_vat = helper("yht_company_vat")
		self.assertEqual(yht_company_vat(frappe._dict()), "")
		self.assertEqual(yht_company_vat(frappe._dict(company="does-not-exist")), "")

	def test_the_vat_line_prints_on_both_block_formats(self):
		"""The two formats that carry the VAT / bank block (spec Step 9)."""
		for print_format, doctype in (
			("KATC Proforma Invoice", "Sales Order"),
			("KATC Quotation No LH", "Quotation"),
		):
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			doc = frappe.get_doc(doctype, name)
			vat = (frappe.db.get_value("Company", doc.company, "tax_id") or "").strip()
			if not vat:
				self.skipTest(f"{doc.company} has no tax_id")
			with self.subTest(print_format=print_format):
				html = render(doctype, name, print_format, no_letterhead=1)
				self.assertIn("VAT #", html, "spec Step 10's first line is missing")
				self.assertIn(vat, html)

	def test_the_bank_block_labels_match_the_spec(self):
		"""Step 10 writes `BANK DETAILS :` / `BANK NAME :` / `IBAN :`."""
		name = artefact_or_any("Quotation")
		if not name:
			self.skipTest("no submitted Quotation")
		if not helper("yht_bank_details")().get("iban"):
			self.skipTest("no matching Bank Account on this site — OQ-1")
		html = render("Quotation", name, "KATC Quotation No LH", no_letterhead=1)
		for label in ("BANK DETAILS :", "BANK NAME :", "IBAN :"):
			with self.subTest(label=label):
				self.assertIn(label, html)


class TestPrintedTaxColumn(FrappeTestCase):
	"""The TAX AMT column has to add up to the VAT Amount printed below it.

	Nothing in the original 87 methods asserted a single printed NUMBER, and this
	is the one document in the change a tax authority reads. A document-level rate
	applied to every line silently overstates the moment one line is zero-rated,
	a second `On Net Total` charge exists, or a charge is `Actual` (rate 0, so the
	whole column printed `0.00`).
	"""

	def taxed_invoice(self):
		for name in frappe.get_all(
			"Sales Invoice",
			filters={"docstatus": 1},
			pluck="name",
			limit=40,
			order_by="modified desc",
		):
			doc = frappe.get_doc("Sales Invoice", name)
			if doc.get("total_taxes_and_charges") and doc.get("items"):
				return doc
		return None

	def test_the_helper_splits_the_document_tax_across_the_rows(self):
		doc = self.taxed_invoice()
		if not doc:
			self.skipTest("no submitted Sales Invoice carries tax")
		per_row = helper("yht_row_taxes")(doc)
		self.assertTrue(
			per_row,
			f"{doc.name}: nothing was read off taxes[].item_wise_tax_detail",
		)
		self.assertAlmostEqual(
			sum(per_row.values()),
			flt(doc.total_taxes_and_charges),
			places=2,
			msg=f"{doc.name}: the per-row split does not add up to the document tax",
		)

	def test_the_helper_degrades_on_a_document_with_no_taxes(self):
		"""Empty dict, so the format falls back to its own arithmetic."""
		self.assertEqual(helper("yht_row_taxes")(frappe._dict(items=[], taxes=[])), {})

	def test_an_actual_charge_is_not_spread_across_the_lines(self):
		"""A freight row belongs to no line's VAT — and it DOES carry a detail map.

		🔴 THE PREMISE THIS TEST USED TO CARRY WAS FALSE. ERPNext calls
		`set_item_wise_tax` for every charge type unless the document is
		consolidated or carries `dont_recompute_tax`
		(`erpnext/controllers/taxes_and_totals.py:544-545`), and distributes an
		`Actual` charge across the lines as
		`item.net_amount * actual / doc.net_total` (`:517-518`). So the freight row
		is built here the way ERPNext builds it — 200.00 split 50/150 across A and
		B — and the helper still has to keep it out of the VAT column. A row shaped
		the way this test used to shape it (no detail at all) would pass whether
		the guard worked or not.

		The membership test is `Account.account_type`, so the two rows are put on
		real accounts of each kind, resolved from the site rather than named.
		"""
		tax_account = frappe.db.get_value("Account", {"account_type": "Tax", "is_group": 0}, "name")
		other_account = frappe.db.get_value(
			"Account", {"account_type": ("!=", "Tax"), "root_type": "Expense", "is_group": 0}, "name"
		)
		if not tax_account or not other_account:
			self.skipTest("site has no Tax and non-Tax account pair to discriminate with")
		doc = frappe._dict(
			items=[
				frappe._dict(name="r1", item_code="A", net_amount=100.0),
				frappe._dict(name="r2", item_code="B", net_amount=300.0),
			],
			taxes=[
				frappe._dict(
					charge_type="On Net Total",
					account_head=tax_account,
					item_wise_tax_detail='{"A": [15.0, 15.0], "B": [15.0, 45.0]}',
					tax_amount_after_discount_amount=60.0,
				),
				# Freight — and ERPNext DID distribute it across the lines:
				# 100/400 * 200 = 50 and 300/400 * 200 = 150.
				frappe._dict(
					charge_type="Actual",
					account_head=other_account,
					item_wise_tax_detail='{"A": [0.0, 50.0], "B": [0.0, 150.0]}',
					tax_amount_after_discount_amount=200.0,
				),
			],
			total_taxes_and_charges=260.0,
		)
		per_row = helper("yht_row_taxes")(doc)
		self.assertEqual(
			{k: round(v, 2) for k, v in per_row.items()},
			{"r1": 15.0, "r2": 45.0},
			"the 200.00 freight charge reached the per-line VAT column",
		)
		self.assertAlmostEqual(
			sum(per_row.values()),
			60.0,
			places=2,
			msg="the column must sum to the VAT, leaving 200.00 as Other Charges",
		)

	def test_an_actual_charge_on_a_TAX_account_stays_in_the_column(self):
		"""The opposite error, and it is on the client's own data.

		`KSIN-26-0092` carries ONE tax row: `Actual`, SAR 1.05, on
		`200602 - VAT OUTPUT 15%`. That IS the invoice's VAT. Excluding every
		`Actual` row — the obvious over-correction — would print a 0.00 VAT column
		on a tax invoice and relabel the tax as `Other Charges`.
		"""
		tax_account = frappe.db.get_value("Account", {"account_type": "Tax", "is_group": 0}, "name")
		if not tax_account:
			self.skipTest("site has no Tax account")
		doc = frappe._dict(
			items=[frappe._dict(name="r1", item_code="A", net_amount=7.0)],
			taxes=[
				frappe._dict(
					charge_type="Actual",
					account_head=tax_account,
					item_wise_tax_detail='{"A": [15.0, 1.05]}',
					tax_amount_after_discount_amount=1.05,
				)
			],
			total_taxes_and_charges=1.05,
		)
		per_row = helper("yht_row_taxes")(doc)
		self.assertAlmostEqual(
			per_row.get("r1", 0.0),
			1.05,
			places=2,
			msg="VAT entered as an Actual charge was dropped out of the VAT column",
		)

	def test_the_printed_tax_column_sums_to_the_printed_vat_amount(self):
		doc = self.taxed_invoice()
		if not doc:
			self.skipTest("no submitted Sales Invoice carries tax")
		body = format_body(render("Sales Invoice", doc.name, "KATC Tax Invoice", no_letterhead=1))

		printed = []
		for row in re.findall(r"<tr>(.*?)</tr>", body, flags=re.S):
			cells = re.findall(r'<td class="num">(.*?)</td>', row, flags=re.S)
			# rate | ex-VAT | TAX AMT | total inc. VAT
			if len(cells) == 4:
				printed.append(money_value(cells[2]))

		self.assertEqual(
			len(printed), len(doc.items), "one TAX AMT cell per item row, no more"
		)
		self.assertAlmostEqual(
			sum(printed),
			flt(doc.total_taxes_and_charges),
			delta=0.01 * len(printed) + 0.01,
			msg=f"{doc.name}: the TAX AMT column does not sum to the VAT Amount below it",
		)


# =========================================================== buttons / wiring


class TestButtonsAndWiring(FrappeTestCase):
	"""Checks 44-48."""

	def test_the_button_js_is_registered_for_exactly_the_four_doctypes(self):
		# check 44
		registered = frappe.get_hooks("doctype_js") or {}
		carrying = set()
		for doctype, paths in registered.items():
			paths = paths if isinstance(paths, list) else [paths]
			if any("katc_print_buttons.js" in p for p in paths):
				carrying.add(doctype)
		self.assertEqual(
			carrying,
			set(BUTTON_DOCTYPES),
			"katc_print_buttons.js must be registered under doctype_js for exactly the four doctypes",
		)

	def test_every_jinja_method_resolves(self):
		"""check 45 — gotcha 25.

		`get_jinja_hooks` resolves EVERY registered path when it builds the
		environment, so one unresolved attribute 500s the whole env — and /login is
		a website page. This is the cheap guard.
		"""
		registered = frappe.get_hooks("jinja", {}).get("methods") or []
		for path in NEW_JINJA_METHODS:
			with self.subTest(path=path):
				self.assertIn(path, registered, f"{path} is not registered in hooks.py")
				self.assertTrue(callable(frappe.get_attr(path)), f"{path} does not resolve")

		# Deliberately NOT a sweep over every installed app's registered paths.
		# `get_obj_dict_from_paths` tries `frappe.get_module(path)` FIRST and only
		# then `frappe.get_attr`, so a whole-MODULE registration is legal — and
		# frappe core ships one (`frappe.utils.jinja_globals`). `callable()` rejects
		# a module, so the sweep failed on frappe's own hook and proved nothing
		# about this change.

	def test_the_js_and_the_module_agree_on_the_letterhead_name(self):
		"""check 46 — the name is duplicated between two files by necessity."""
		self.assertIn(katc_letterhead().KATC_LETTER_HEAD, js_source())

	def test_the_js_names_only_formats_that_exist(self):
		"""check 47 — catches a typo in a `format=` before a user does."""
		source = js_source()
		named = {s["format"] for s in button_specs(source) if s["format"]}
		self.assertTrue(named, "no button map could be parsed out of katc_print_buttons.js")
		known = {f for f, _dt in FORMATS}
		self.assertTrue(
			named <= known,
			f"the JS names a format that is not in FORMATS: {sorted(named - known)}",
		)
		for print_format in named:
			with self.subTest(print_format=print_format):
				self.assertTrue(
					frappe.db.exists("Print Format", print_format),
					f"the JS points at {print_format}, which does not exist",
				)

	def test_the_flags_land_on_the_right_paths(self):
		"""check 48 — the letterhead flags land on the right paths.

		Twelve buttons since the 2026-08-27 rework: Print / With Arabic / Proforma /
		Without LH on Quotation and Sales Order, Print / Without LH on Sales Invoice and
		Delivery Note. Those last two get no Arabic button because both already print
		the Arabic item name inside the item cell — a column would print it twice.

		Eight letterhead= paths and four no_letterhead=1, and the two sets are disjoint
		by construction: the letterhead is now the BUTTON's job for every doctype, since
		the shared templates render one whenever they are handed one.
		"""
		specs = button_specs(js_source())
		# Four on Quotation and Sales Order (Print / With Arabic / Proforma / Without
		# LH), two on Sales Invoice and Delivery Note — those two already print the
		# Arabic name inline, so a column would duplicate it and they get no Arabic
		# button.
		self.assertEqual(len(specs), 12, "twelve buttons across the four doctypes")

		without = [s for s in specs if s["no_letterhead"] == "1"]
		self.assertEqual(
			{s["format"] for s in without},
			{
				"KATC Delivery Note",
				"KATC Tax Invoice",
				"KATC Sales Order No LH",
				"KATC Quotation No LH",
			},
			"no_letterhead=1 belongs on exactly the four Print Without LH paths",
		)
		self.assertEqual(len(without), 4)
		for spec in without:
			with self.subTest(print_format=spec["format"]):
				self.assertIsNone(
					spec["letterhead"],
					"a Print Without LH path must not also pass letterhead=",
				)

		with_lh = [s for s in specs if s["letterhead"]]
		self.assertEqual(len(with_lh), 8, "letterhead= belongs on exactly eight paths")
		self.assertEqual(
			{s["format"] for s in with_lh},
			{
				"KATC Delivery Note",
				"KATC Tax Invoice",
				"KATC Sales Order",
				"KATC Sales Order Arabic",
				"KATC Proforma Invoice",
				"KATC Quotation",
				"KATC Quotation Arabic",
				"KATC Quotation Proforma",
			},
		)
		for spec in with_lh:
			with self.subTest(print_format=spec["format"]):
				self.assertEqual(
					spec["no_letterhead"], "0", "a with-letterhead path must pass no_letterhead=0"
				)
				self.assertIn(
					EXPECTED_LETTER_HEAD.split()[0],
					spec["letterhead"],
					"the explicit letterhead= is what stops get_letter_head falling back to "
					"doc.letter_head and printing the incumbent image",
				)

	def test_every_label_is_translated_and_top_level(self):
		"""check 57's automatable half — the incumbent's exact labels."""
		source = js_source()
		for label in ("Print PDF", "Print Without LH", "Print with Arabic", "Proforma Invoice"):
			with self.subTest(label=label):
				self.assertRegex(
					source,
					r"__\(\s*[\"']" + re.escape(label) + r"[\"']\s*\)",
					f"{label} must go through __()",
				)
		self.assertNotIn(
			"add_custom_button(__(\"Print PDF\"), () => {}, __(",
			source,
			"buttons must be top-level, with no group argument",
		)

	def test_the_js_guards_against_double_registration(self):
		"""One file under four doctypes loads once per doctype visited; without a
		guard the `refresh` handlers stack up and the buttons duplicate."""
		source = js_source()
		self.assertIn("frappe.provide", source)
		self.assertRegex(source, r"bound", "no idempotency guard flag in katc_print_buttons.js")

	def test_the_url_uses_download_pdf_and_carries_no_signing_key(self):
		"""A `key=` would create a guest-readable link to a customer document."""
		source = js_source()
		self.assertIn("frappe.utils.print_format.download_pdf", source)
		self.assertNotRegex(source, r"[?&]key=", "no signing key goes in the query string")
		self.assertIn("encodeURIComponent", source)


# ================================================================= regression


class TestRegression(FrappeTestCase):
	"""Checks 49-52. Nothing existing may move."""

	def test_the_six_incumbent_formats_are_untouched(self):
		# check 49
		for print_format, doctype in INCUMBENT_FORMATS:
			with self.subTest(print_format=print_format):
				row = frappe.db.get_value(
					"Print Format",
					print_format,
					["doc_type", "disabled", "print_format_type"],
					as_dict=True,
				)
				self.assertTrue(row, f"{print_format} was deleted")
				self.assertEqual(row.doc_type, doctype)
				self.assertFalse(row.disabled)
				self.assertEqual(row.print_format_type, "Jinja")

	def test_the_incumbent_formats_still_render(self):
		# check 49
		for print_format, doctype in INCUMBENT_FORMATS:
			name = submitted(doctype)
			if not name:
				continue
			with self.subTest(print_format=print_format):
				html = frappe.get_print(doctype, name, print_format=print_format)
				self.assertGreater(len(html), 2000)

	def test_sales_invoice_has_no_pinned_default(self):
		"""check 50 — ksa_compliance owns Sales Invoice printing until onboarding."""
		self.assertFalse(frappe.db.get_value("DocType", "Sales Invoice", "default_print_format"))

	def test_the_defaults_still_point_at_the_yht_set(self):
		# check 51
		self.assertEqual(
			setup.DEFAULT_PRINT_FORMATS,
			{
				"Delivery Note": "YHT Delivery Note",
				"Quotation": "YHT Quotation",
				"Sales Order": "YHT Sales Order",
				"Purchase Invoice": "YHT Purchase Invoice",
				"Journal Entry": "YHT Journal Entry",
			},
			"DEFAULT_PRINT_FORMATS was changed — this change re-defaults nothing",
		)
		for doctype, print_format in setup.DEFAULT_PRINT_FORMATS.items():
			with self.subTest(doctype=doctype):
				self.assertEqual(
					frappe.db.get_value("DocType", doctype, "default_print_format"), print_format
				)

	def test_no_katc_format_became_a_doctype_default(self):
		for doctype in BUTTON_DOCTYPES:
			with self.subTest(doctype=doctype):
				default = frappe.db.get_value("DocType", doctype, "default_print_format") or ""
				self.assertFalse(default.startswith("KATC"), f"{doctype} was re-defaulted to {default}")

	def test_the_payment_assist_bank_account_contract_holds(self):
		"""check 52 — `api/payment_assist.py` builds Payment Entries field by field
		precisely because Bank Account read is denied."""
		import inspect

		from yht_custom.api import payment_assist

		flat = re.sub(r"\s+", " ", inspect.getsource(payment_assist))
		self.assertIsNone(
			re.search(r"get_doc\(\s*[\"']Bank Account[\"']", flat),
			"payment_assist reopened the Bank Account controller",
		)

	def test_nothing_was_deleted(self):
		"""Belt and braces on the spec's 'nothing is deleted'."""
		for name in (INCUMBENT_LETTER_HEAD,):
			with self.subTest(record=name):
				self.assertTrue(frappe.db.exists("Letter Head", name))
		for branch in frappe.get_all("Branch", pluck="name"):
			with self.subTest(branch=branch):
				self.assertTrue(
					frappe.db.exists("Letter Head", letterhead.letter_head_name(branch))
				)


# ================================================== artefact fidelity (53-59)


class TestArtefactFidelity(FrappeTestCase):
	"""Checks 53-59 — the automatable half of the Tester's manual pass.

	The visual diff itself (glyph positions, Arabic shaping, bidi) still has to be
	done by eye against `.pipeline/client-artefacts/*.pdf`; these tests pin the
	strings and structure that a rendering can be checked against, so a regression
	is caught by the suite rather than by the client.
	"""

	# `test_the_artefact_pdfs_are_still_in_the_repo` (check 53's first half) was
	# REMOVED, not silenced. `.gitignore` excludes `.pipeline/`, so the reference
	# PDFs are pipeline scaffolding and never ship with the installed app: the test
	# could only ever `skipTest`, on every bench, forever. Keeping the reference
	# artefacts alive is a repo-hygiene job, not something a Frappe test can hold.

	def test_the_delivery_note_prices_nothing(self):
		"""check 53 — the artefact deliberately shows Sl NO / Item Name / Quantity
		only. A rate or an amount on a customer delivery note is a defect."""
		name = artefact_or_any("Delivery Note")
		if not name:
			self.skipTest("no submitted Delivery Note")
		html = render("Delivery Note", name, "KATC Delivery Note", no_letterhead=1)
		self.assertIn("DELIVERY NOTE", html)
		for banned in ("Unit Rate", "Grand Total", "Total (Excluding VAT)", "In Words"):
			with self.subTest(banned=banned):
				self.assertNotIn(banned, html)
		for expected in ("Delivered By", "Received By", "Terms and Conditions"):
			with self.subTest(expected=expected):
				self.assertIn(expected, html)

	def test_the_tax_invoice_carries_its_artefact_labels(self):
		# check 53
		name = artefact_or_any("Sales Invoice")
		if not name:
			self.skipTest("no submitted Sales Invoice")
		html = plain_arabic(render("Sales Invoice", name, "KATC Tax Invoice", no_letterhead=1))
		for label in (
			"TAX INVOICE",
			"فاتورة ضريبية",
			"Building No.",
			"District",
			"Post Code",
			"Additional No.",
			"CR Number",
			"Total Taxable Amount",
		):
			with self.subTest(label=label):
				self.assertIn(label, html)

	def test_the_bilingual_labels_use_a_hyphen_not_a_colon(self):
		"""check 55 — RTL/bidi.

		A colon immediately before an LTR run inside an RTL block is relocated to
		the visual left by the bidi algorithm, so `الرقم الضريبي:` renders as
		`:الرقم الضريبي`. The client's own artefacts use a hyphen.
		"""
		name = artefact_or_any("Sales Invoice")
		if not name:
			self.skipTest("no submitted Sales Invoice")
		html = render("Sales Invoice", name, "KATC Tax Invoice", no_letterhead=1)
		text = re.sub(r"<[^>]+>", " ", html)
		offenders = re.findall(r"[؀-ۿ]+\s*:", text)
		self.assertEqual(offenders, [], f"colon after Arabic label(s): {offenders[:5]}")

	def test_the_letterhead_has_no_bare_colon_before_a_number(self):
		"""check 55 — the supplied HTML writes `الرمز البريدي: 34429` and
		`س.ت: 2051226328`. Split the cells or wrap the numeric run in dir="ltr"."""
		content = frappe.db.get_value(
			"Letter Head", katc_letterhead().KATC_LETTER_HEAD, "content"
		) or ""
		text = re.sub(r"<[^>]+>", " ", content)
		offenders = re.findall(r"[؀-ۿ]+\s*:\s*[0-9+]", text)
		self.assertEqual(offenders, [], f"bidi hazard in the letterhead: {offenders[:5]}")

	def test_the_letterhead_repeats_via_thead(self):
		"""check 54 — the MARKUP PRECONDITION only. Not the PDF behaviour.

		What this proves: every format opens with a `<thead>` on the outer table
		and allows `page-break-inside: auto` on the outer cell, which is what a
		working build needs in order to repeat the header on page 2+ (the client's
		`quote Print 1.pdf` does repeat it, on their bench).

		🔴 WHAT IT DOES NOT PROVE: that the header actually repeats here.
		`/usr/bin/wkhtmltopdf` on this box is 0.12.6 WITHOUT patched Qt, so a
		`<thead>` does not repeat on page 2 of a 120-row table — measured, three
		ways, CLAUDE.md gotcha 44. The PDF behaviour is unverified on this build by
		design and is an infrastructure decision (`.pipeline/decisions.md`, Q9),
		not something this assertion can carry.
		"""
		for print_format, _doctype in FORMATS:
			html = format_source(print_format)
			with self.subTest(print_format=print_format):
				self.assertIn("<thead", html, f"{print_format} has no repeating header row")
				self.assertRegex(
					html,
					r"page-break-inside\s*:\s*auto",
					f"{print_format} never allows the outer cell to break across pages",
				)

	def test_the_page_number_spans_are_present(self):
		"""check 56 — the MARKUP PRECONDITION only. Not the printed page number.

		What this proves: every format emits the `page` / `topage` spans that
		frappe extracts into `--footer-html`, which is the only route by which
		`Page N of M` could resolve (a browser print dialog leaves them empty —
		one reason the buttons use `download_pdf`).

		🔴 WHAT IT DOES NOT PROVE: that a page number prints. On this box
		wkhtmltopdf 0.12.6 has no patched Qt, renders nothing from the extracted
		footer file, and `get_pdf` adds `--disable-javascript` so `subst()` could
		not fill the spans even on a patched build — CLAUDE.md gotcha 44. The PDF
		behaviour is separately unverified on this build; see
		`.pipeline/decisions.md`, Q9.
		"""
		for print_format, doctype in FORMATS:
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			html = render(doctype, name, print_format, no_letterhead=1)
			with self.subTest(print_format=print_format):
				self.assertRegex(html, r'class\s*=\s*["\']page["\']')
				self.assertRegex(html, r'class\s*=\s*["\']topage["\']')

	def test_the_footer_is_hidden_in_the_browser_print_view(self):
		"""check 56 — in the browser it would render inline instead."""
		for print_format, _doctype in FORMATS:
			css = (frappe.db.get_value("Print Format", print_format, "css") or "") + (
				format_source(print_format)
			)
			with self.subTest(print_format=print_format):
				self.assertIn("print-format-gutter", css)

	def test_the_printed_bank_is_al_rajhi_not_the_site_default(self):
		"""check 58 / OQ-1 — the site's DEFAULT Bank Account is Saudi National Bank.

		Resolving by `is_default` would print the wrong receiving account on a
		customer-facing quotation.
		"""
		details = helper("yht_bank_details")()
		if not details.get("iban"):
			self.skipTest(
				"OQ-1 unresolved on this site: no Bank Account matches the artefact IBAN, "
				"so the bank block renders empty by design"
			)
		self.assertEqual(details["iban"], ARTEFACT_IBAN)
		self.assertIn("RAJHI", (details["bank"] or "").upper())
		self.assertEqual(details["account_no"], ARTEFACT_ACCOUNT_NO)

		default_account = frappe.db.get_value("Bank Account", {"is_default": 1}, "iban")
		if default_account:
			self.assertNotEqual(
				details["iban"],
				default_account,
				"the block resolved by is_default — Step 10 constraint 2 says resolve by IBAN",
			)

	def test_draft_printing_is_reported(self):
		"""check 59 — `DN Print 1.pdf` is a DRAFT delivery note, so the incumbent
		has `allow_print_for_draft` on. If it is off here, `validate_print_permission`
		throws and the buttons look broken. Reporting is this suite's job; changing
		it is a site-settings decision, not part of this change.
		"""
		allowed = frappe.db.get_single_value("Print Settings", "allow_print_for_draft")
		if not allowed:
			self.skipTest(
				"REPORT: Print Settings.allow_print_for_draft is OFF on this site — "
				"the client's own DN Print 1.pdf is a draft, so the Print PDF button "
				"will throw on any draft document until this is switched on"
			)
		self.assertTrue(allowed)

	def test_a_draft_document_renders_the_draft_titles(self):
		"""Step 6 — `DRAFT DELIVERY NOTE` / `مسودة مذكرة تسليم`."""
		name = artefact_or_any("Delivery Note")
		if not name:
			self.skipTest("no submitted Delivery Note")
		doc = frappe.get_doc("Delivery Note", name)
		doc.docstatus = 0
		html = frappe.get_print(
			"Delivery Note", name, print_format="KATC Delivery Note", doc=doc, no_letterhead=1
		)
		html = plain_arabic(html)
		self.assertIn("DRAFT DELIVERY NOTE", html)
		self.assertIn("مسودة مذكرة تسليم", html)


# =================================================== degenerate documents


class TestDegenerateDocuments(FrappeTestCase):
	"""Edge Cases section — everything that must degrade rather than throw."""

	def test_a_document_with_no_taxes_prints_no_stray_percent(self):
		"""`VAT Amount {{rate}}%` must not become `VAT Amount %`."""
		for print_format, doctype in (
			("KATC Tax Invoice", "Sales Invoice"),
			("KATC Proforma Invoice", "Sales Order"),
		):
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			doc = frappe.get_doc(doctype, name)
			doc.taxes = []
			doc.total_taxes_and_charges = 0
			with self.subTest(print_format=print_format):
				html = frappe.get_print(
					doctype, name, print_format=print_format, doc=doc, no_letterhead=1
				)
				text = re.sub(r"<[^>]+>", " ", html)
				self.assertNotRegex(
					text, r"VAT\s+Amount\s+%", "a stray % printed with no tax row behind it"
				)

	def test_a_document_with_no_terms_renders(self):
		for print_format, doctype in FORMATS:
			name = artefact_or_any(doctype)
			if not name:
				self.skipTest(f"no submitted {doctype}")
			doc = frappe.get_doc(doctype, name)
			doc.terms = None
			with self.subTest(print_format=print_format):
				self.assertTrue(
					frappe.get_print(doctype, name, print_format=print_format, doc=doc, no_letterhead=1)
				)

	def test_a_zero_discount_still_prints(self):
		"""The artefact prints `- 0.00`, so print it."""
		name = artefact_or_any("Sales Order")
		if not name:
			self.skipTest("no submitted Sales Order")
		doc = frappe.get_doc("Sales Order", name)
		doc.discount_amount = 0
		html = frappe.get_print(
			"Sales Order", name, print_format="KATC Proforma Invoice", doc=doc, no_letterhead=1
		)
		self.assertIn("Discount", html)

	def test_an_empty_arabic_cell_does_not_collapse_the_column(self):
		"""3,857 Item rows and a variable share of child rows carry no Arabic."""
		name = artefact_or_any("Quotation")
		if not name:
			self.skipTest("no submitted Quotation")
		original = getattr(print_helpers, "yht_item_ar", None)
		if original is None:
			self.fail("print_helpers.yht_item_ar does not exist")
		print_helpers.yht_item_ar = lambda row: ""
		try:
			html = render("Quotation", name, "KATC Quotation Arabic", no_letterhead=1)
		finally:
			print_helpers.yht_item_ar = original
		self.assertIn(
			"katc-ar-col", html, "the Arabic column collapsed when every value was empty"
		)

	def test_a_negative_line_discount_is_not_printed(self):
		"""A line priced ABOVE list rate produces a negative 'discount'. The six
		existing formats guard this with `if item_discount > 0`; the new ones follow."""
		name = artefact_or_any("Sales Order")
		if not name:
			self.skipTest("no submitted Sales Order")
		doc = frappe.get_doc("Sales Order", name)
		for row in doc.items:
			row.price_list_rate = max(0, (row.rate or 0) - 100)
		html = frappe.get_print(
			"Sales Order", name, print_format="KATC Proforma Invoice", doc=doc, no_letterhead=1
		)
		text = re.sub(r"<[^>]+>", " ", html)
		self.assertNotRegex(text, r"-\s*\d+\.\d{2}\s*Discount", "a negative discount printed")


# ================================================ branch scoping / permissions


class TestPrintPermissions(FrappeTestCase):
	"""Edge Cases — the print boundary is `validate_print_permission`, not the URL."""

	def test_branch_user_holds_print_on_all_four_doctypes(self):
		perms = {p["parent"]: p for p in setup.BRANCH_USER_PERMISSIONS}
		for doctype in BUTTON_DOCTYPES:
			with self.subTest(doctype=doctype):
				self.assertIn(doctype, perms)
				self.assertTrue(perms[doctype].get("print"), f"Branch User cannot print {doctype}")

	def test_download_pdf_still_validates_before_rendering(self):
		"""`download_pdf` is `@frappe.whitelist(allow_guest=True)`; the boundary is
		`validate_print_permission(doc)` INSIDE it. Nothing here may weaken that."""
		import inspect

		from frappe.utils import print_format as frappe_print_format

		source = inspect.getsource(frappe_print_format.download_pdf)
		self.assertIn("validate_print_permission", source)

	def test_a_branch_user_cannot_print_another_branchs_document(self):
		"""`permission_query_conditions` filters LISTS, not `frappe.get_doc`.

		A branch user who guesses another branch's document name and hits
		`download_pdf` directly is stopped by `validate_print_permission` →
		`has_permission`, which does consult User Permissions.
		"""
		user = "yht-katc-scope@example.com"
		if not frappe.db.exists("Role", "Branch User"):
			self.skipTest("Branch User role not provisioned")
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": user,
					"first_name": "KATC Scope",
					"user_type": "System User",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		doc = frappe.get_doc("User", user)
		if "Branch User" not in {r.role for r in doc.roles}:
			doc.append("roles", {"role": "Branch User"})
			doc.save(ignore_permissions=True)

		company = frappe.db.get_value("Company", {}, "name")
		other = frappe.get_all(
			"Warehouse", filters={"company": company, "is_group": 0}, pluck="name", limit=1
		)
		if not other:
			self.skipTest("no leaf warehouse to scope against")

		if not frappe.db.exists(
			"User Permission", {"user": user, "allow": "Company", "for_value": company}
		):
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": user,
					"allow": "Company",
					"for_value": company,
					"apply_to_all_doctypes": 1,
				}
			).insert(ignore_permissions=True)

		foreign = frappe.db.get_value(
			"Sales Invoice", {"docstatus": 1, "company": ["!=", company]}, "name"
		)
		if not foreign:
			self.skipTest("single-company site — nothing out of scope to attempt")

		frappe.clear_cache(user=user)
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				frappe.get_print("Sales Invoice", foreign, print_format="KATC Tax Invoice")
		finally:
			frappe.set_user("Administrator")


if __name__ == "__main__":
	unittest.main()


class TestBuyerBlockFields(FrappeTestCase):
	"""The buyer block read four fields and three of them were the wrong ones."""

	def test_the_building_number_is_not_printed_as_the_street(self):
		"""🔴 THE REGRESSION. `address_line1` holds the BUILDING NUMBER on this site.

		Reading it as the street printed `6823` under "Street Name" on
		`VTSI-KT-6925` while the incumbent printed "Prince Sultan Road".
		"""
		helper = frappe.get_attr("yht_custom.print_helpers.yht_national_address")
		# `regexp` is not a frappe filter operator — parameterised SQL instead.
		rows = frappe.db.sql(
			"""SELECT name FROM `tabAddress`
			   WHERE country = %s AND address_line1 REGEXP '^[0-9]+$'
			         AND IFNULL(address_line2, '') <> '' LIMIT 1""",
			("Saudi Arabia",),
		)
		address = rows[0][0] if rows else None
		if not address:
			self.skipTest("no address with a numeric line1 and a line2")
		line1, line2 = frappe.db.get_value("Address", address, ["address_line1", "address_line2"])
		out = helper(frappe._dict(customer_address=address), "customer_address")
		self.assertEqual(out["street"], cstr(line2).strip(), "street must come from address_line2")
		self.assertNotEqual(out["street"], cstr(line1).strip(), "the building number reached the street cell")
		self.assertEqual(out["building"], cstr(line1).strip(), "building must come from the numeric line1")

	def test_a_one_line_address_keeps_its_street(self):
		"""The other shape: no line2, and line1 is a real street rather than a number.

		215 of 577 addresses here are written that way. Treating line1 as the
		building number for those would blank the street instead of fixing it.
		"""
		helper = frappe.get_attr("yht_custom.print_helpers.yht_national_address")
		rows = frappe.db.sql(
			"""SELECT name FROM `tabAddress`
			   WHERE country = %s AND address_line1 NOT REGEXP '^[0-9]+$'
			         AND IFNULL(address_line1, '') <> ''
			         AND IFNULL(address_line2, '') = '' LIMIT 1""",
			("Saudi Arabia",),
		)
		address = rows[0][0] if rows else None
		if not address:
			self.skipTest("no single-line address on this site")
		line1 = frappe.db.get_value("Address", address, "address_line1")
		out = helper(frappe._dict(customer_address=address), "customer_address")
		self.assertEqual(out["street"], cstr(line1).strip())
		self.assertEqual(out["building"], "", "a non-numeric line1 is not a building number")

	def test_a_missing_address_still_returns_every_key(self):
		helper = frappe.get_attr("yht_custom.print_helpers.yht_national_address")
		out = helper(frappe._dict(customer_address=None), "customer_address")
		for key in ("building", "street", "district", "city", "pincode", "additional", "country"):
			self.assertEqual(out[key], "", f"{key} must default to empty, never None")

	def test_the_buyer_vat_falls_back_to_the_customer(self):
		"""`doc.tax_id` is NULL on imported invoices; the Customer still has one."""
		vat = frappe.get_attr("yht_custom.print_helpers.yht_party_vat")
		customer = frappe.db.get_value("Customer", {"tax_id": ["!=", ""]}, "name")
		if not customer:
			self.skipTest("no customer carries a tax_id")
		expected = cstr(frappe.db.get_value("Customer", customer, "tax_id")).strip()
		self.assertEqual(vat(frappe._dict(customer=customer, tax_id=None)), expected)
		self.assertEqual(vat(frappe._dict(customer=customer, tax_id="")), expected)

	def test_the_documents_own_vat_wins(self):
		"""What was true at invoice time is what ZATCA reported. Do not overwrite it."""
		vat = frappe.get_attr("yht_custom.print_helpers.yht_party_vat")
		customer = frappe.db.get_value("Customer", {"tax_id": ["!=", ""]}, "name")
		if not customer:
			self.skipTest("no customer carries a tax_id")
		self.assertEqual(vat(frappe._dict(customer=customer, tax_id="300000000000003")), "300000000000003")

	def test_no_party_and_no_tax_id_is_blank_not_none(self):
		vat = frappe.get_attr("yht_custom.print_helpers.yht_party_vat")
		self.assertEqual(vat(frappe._dict(customer=None, tax_id=None)), "")


# ================================================== the shared-template refactor


class TestSharedTemplates(FrappeTestCase):
	"""A variant is a FLAG, not a hand-synced copy of the whole layout."""

	def test_the_variants_are_shims_not_copies(self):
		"""🔴 The old pair carried a comment reading 'KATC Quotation and KATC Quotation
		Arabic must stay identical outside the katc-ar-col cells — edit BOTH, or the
		check fails.' That trap would have multiplied from one pair to four."""
		for print_format in SHIMMED:
			with self.subTest(print_format=print_format):
				# The RAW record, not format_source — that helper resolves the include.
				html = frappe.db.get_value("Print Format", print_format, "html") or ""
				self.assertIn("{% include", html, f"{print_format} is not a shim")
				self.assertLess(
					len(html), 260, f"{print_format} still carries a copy of the layout"
				)

	def test_every_included_template_ships(self):
		import os
		import re

		for print_format in SHIMMED:
			html = frappe.db.get_value("Print Format", print_format, "html") or ""
			for path in re.findall(r'{%\s*include\s+"([^"]+)"', html):
				with self.subTest(print_format=print_format, path=path):
					# "yht_custom/templates/..." resolves under the app's parent dir.
					full = os.path.join(
						os.path.dirname(frappe.get_app_path("yht_custom")), path
					)
					self.assertTrue(os.path.exists(full), f"{path} does not ship")

	def test_the_arabic_column_is_a_flag(self):
		for print_format in ("KATC Quotation Arabic", "KATC Sales Order Arabic"):
			with self.subTest(print_format=print_format):
				html = format_source(print_format)
				self.assertIn("katc_show_arabic", html)

	def test_the_proforma_serves_both_doctypes(self):
		"""One template, two doctypes — so every Sales-Order-only field must be read
		with doc.get(). A Quotation has no delivery_date, and an unguarded attribute
		renders frappe's DebugUndefined marker straight onto a customer document."""
		import os

		path = os.path.join(
			frappe.get_app_path("yht_custom"), "templates", "includes", "katc",
			"proforma_invoice.html",
		)
		body = open(path, encoding="utf-8").read()
		self.assertNotIn("doc.delivery_date", body, "unguarded Sales-Order-only field")
		self.assertEqual(
			frappe.db.get_value("Print Format", "KATC Proforma Invoice", "doc_type"),
			"Sales Order",
		)
		self.assertEqual(
			frappe.db.get_value("Print Format", "KATC Quotation Proforma", "doc_type"),
			"Quotation",
		)

	def test_sales_invoice_and_delivery_note_have_no_arabic_button(self):
		"""🔴 Both already print the Arabic name inside the item cell, so a column
		would print it twice. Measured on the formats, not assumed."""
		specs = button_specs(js_source())
		for doctype in ("Sales Invoice", "Delivery Note"):
			labels = [s["label"] for s in specs if s.get("doctype") == doctype]
			if not labels:
				continue
			with self.subTest(doctype=doctype):
				self.assertFalse(
					[l for l in labels if "Arabic" in l],
					f"{doctype} already prints Arabic inline — a column duplicates it",
				)


# ============================================ the Arabic column must never overflow


class TestArabicColumnFit(FrappeTestCase):
	"""The three conditions that make a right-aligned RTL line anchor correctly.

	🔴 These are the CI gate. The objective check — reading the drawn column rules and
	the Arabic glyph boxes out of a PDF rendered through `download_pdf` — lives in
	`scripts/katc_ar_overflow.py` and needs `pdfplumber`, which is deliberately NOT
	installed on the bench (it also runs live client sites). Run it at acceptance:

	    python scripts/katc_ar_overflow.py *.pdf

	It is two-sided-verified: it FAILS the pre-fix build (17 escaping glyphs, worst
	+53.27 pt) and passes 39 of 39 real documents after. The invariants below are what
	the render proved makes a line safe, so they are a sound regression barrier.
	"""

	def _lines(self, text):
		from yht_custom import print_helpers

		row = frappe._dict({"doctype": "Sales Order Item", "custom_item_name_in_arabic": text})
		return print_helpers.yht_item_ar_lines(row)

	def test_every_line_is_anchored_at_both_ends(self):
		"""U+200F at ONE end does nothing — measured. Both ends, or it mis-anchors."""
		from yht_custom.print_helpers import RLM

		for text in ("بولت مجلفن مع صامولة ووردة M16",
		             "شفة لحام العنق حديد كاربون مزور اساس اوروبا 4\"",
		             "مواد عامة"):
			for line in self._lines(text):
				with self.subTest(text=text[:20], line=line[:20]):
					self.assertTrue(line.startswith(RLM), "line does not start with U+200F")
					self.assertTrue(line.endswith(RLM), "line does not end with U+200F")

	def test_no_line_contains_a_plain_space(self):
		"""A single U+0020 is enough to mis-anchor the whole line."""
		for text in ("بولت مجلفن مع صامولة ووردة M16", "محبس حديد مصبوب ساق الجدعية - او اس"):
			for line in self._lines(text):
				with self.subTest(line=line[:24]):
					self.assertNotIn(" ", line, "a plain space survived; use U+00A0")

	def test_a_row_with_no_arabic_yields_no_lines(self):
		self.assertEqual(self._lines(""), [])
		self.assertEqual(self._lines("   "), [])

	def test_the_inline_formats_get_the_same_anchoring(self):
		"""Proforma / Tax Invoice / Delivery Note print Arabic inline and carried the
		same defect — measured worse, 88 of 141 glyphs past the rule."""
		from yht_custom import print_helpers
		from yht_custom.print_helpers import RLM

		row = frappe._dict({"doctype": "Sales Order Item",
		                    "custom_item_name_in_arabic": "بولت مجلفن مع صامولة"})
		out = print_helpers.yht_item_ar_rtl(row)
		self.assertTrue(out.startswith(RLM) and out.endswith(RLM))
		self.assertNotIn(" ", out)
		self.assertEqual(print_helpers.yht_item_ar_rtl(frappe._dict({"doctype": "Sales Order Item"})), "")

	def test_the_budget_is_derived_from_the_column_width(self):
		"""The Python constant and the template's `width:34%` must not drift apart."""
		import os
		import re

		from yht_custom import print_helpers

		# The Proforma's table carries eight columns, so its Arabic column is narrower
		# and it passes its own percentage to yht_item_ar_lines. Whatever the number,
		# the template's `width:N%` and the number it passes must agree.
		for f, expected in (("quotation.html", print_helpers.KATC_AR_COL_PCT),
		                    ("sales_order.html", print_helpers.KATC_AR_COL_PCT),
		                    ("proforma_invoice.html", None)):
			path = os.path.join(frappe.get_app_path("yht_custom"), "templates", "includes", "katc", f)
			body = open(path, encoding="utf-8").read()
			m = re.search(r'katc-ar-col"\s+style="width:\s*([0-9.]+)%', body)
			with self.subTest(template=f):
				self.assertTrue(m, f"no Arabic column width found in {f}")
				width = float(m.group(1))
				if expected is not None:
					self.assertEqual(
						width, expected, "the template width and KATC_AR_COL_PCT have drifted apart"
					)
				passed = re.search(r"yht_item_ar_lines\(row,\s*([0-9.]+)\)", body)
				if passed:
					self.assertEqual(
						float(passed.group(1)),
						width,
						f"{f} declares width:{width}% but wraps to {passed.group(1)}%",
					)
		self.assertGreater(print_helpers.ar_budget_em(), 0)
		self.assertLess(print_helpers.ar_budget_em(22), print_helpers.ar_budget_em(34))

	def test_a_long_name_wraps_rather_than_overflowing(self):
		long = "محبس حديد مصبوب ساق الجدعية - او اس & واي مع فلنجة أساس امريكي 10\""
		lines = self._lines(long)
		self.assertGreater(len(lines), 1, "a 60-character name did not wrap at all")

	def test_a_short_name_is_not_wrapped_needlessly(self):
		"""The complaint that started this: short names split into three lines."""
		self.assertEqual(len(self._lines("مواد عامة")), 1)
		self.assertEqual(len(self._lines("كوع زاوية سنة بيس")), 1)


class TestArabicLabelsAreAnchored(FrappeTestCase):
	"""Every Arabic LITERAL in every format must be RLM-wrapped and NBSP-joined.

	🔴 The item names were fixed first and the LABELS were missed, so the column
	headings drew on top of each other — `كمية` (QTY) over `اسم الصنف بالعربي`,
	`الضريبة` over `غير شامل الضريبة`, `الرقم الإضافي` over its own value. Same bidi
	anchoring bug, same two conditions: no U+0020, strong RTL at both ends.

	Only MULTI-WORD runs actually mis-anchor — a single token already satisfies both
	conditions — so that is what this asserts, keeping it honest rather than pedantic.
	"""

	AR = "؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿"

	def _unanchored(self, body: str):
		import re

		rlm = "‏"
		run = re.compile(f"[{self.AR}][{self.AR}]*(?:[ ]+[{self.AR}0-9%]+)+")
		split = re.compile(r"(\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}|<[^>]+>)", re.S)
		out = []
		for part in split.split(body):
			if part.startswith(("{{", "{%", "{#", "<")):
				continue
			for m in run.finditer(part):
				s = m.group(0)
				if not (s.startswith(rlm) and s.endswith(rlm)):
					out.append(s)
		return out

	def test_no_template_carries_a_bare_multi_word_arabic_run(self):
		import glob
		import os

		base = os.path.join(frappe.get_app_path("yht_custom"), "templates", "includes", "katc")
		found = False
		for path in sorted(glob.glob(os.path.join(base, "*.html"))):
			found = True
			with self.subTest(template=os.path.basename(path)):
				bare = self._unanchored(open(path, encoding="utf-8").read())
				self.assertFalse(bare, f"unanchored Arabic in {os.path.basename(path)}: {bare[:3]}")
		self.assertTrue(found, "no KATC templates found — the check would pass vacuously")

	def test_no_print_format_record_carries_a_bare_multi_word_arabic_run(self):
		for print_format, _dt in FORMATS:
			html = frappe.db.get_value("Print Format", print_format, "html") or ""
			with self.subTest(print_format=print_format):
				bare = self._unanchored(html)
				self.assertFalse(bare, f"unanchored Arabic in {print_format}: {bare[:3]}")

	def test_the_check_would_catch_a_regression(self):
		"""A guard that cannot fail is not a guard."""
		self.assertTrue(self._unanchored('<td>غير شامل الضريبة</td>'))
		self.assertFalse(self._unanchored('<td>‏غير شامل الضريبة‏</td>'))
		self.assertFalse(self._unanchored("<td>وصف</td>"), "a single token needs no anchoring")
