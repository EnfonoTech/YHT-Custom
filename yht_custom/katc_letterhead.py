# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""The client's redesigned bilingual A4 stationery, as an HTML `Letter Head`.

WHAT THE CLIENT SUPPLIED. `.pipeline/client-artefacts/Kathoom_A4_Letterhead_
Recreated_HTML.html` — a standalone A4 page: English block left, roundel centre,
Arabic block right, navy rule, red/navy accent bar. Three things in it cannot
survive being pasted into a Letter Head, and all three are corrected here.

1. **It is a page, not a fragment.** `<!DOCTYPE>`, `@page`, `html, body {
   width:210mm; min-height:297mm }` and a 245 mm spacer div. A Letter Head's
   `content` is injected INTO a print page; those rules would wreck every format
   that carried them.
2. **It lays out with `display:flex`.** wkhtmltopdf 0.12.x runs an old WebKit
   whose flexbox support is unreliable, so the header is a `<table>` here —
   English 47% / logo 23% / Arabic 47%, the artefact's own proportions.
3. **It carries the logo as a ~320 KB base64 data URI.** Letter Head `content` is
   re-run through `frappe.utils.jinja.render_template()` on EVERY print and is
   scrubbed by `scrub_urls`. The logo ships as an asset instead (Q1) — which is
   what the incumbent image letterhead already does successfully on this site.

WHAT IT DELIBERATELY DOES NOT DO. `is_default` stays 0 and
`Company.default_letter_head` is not touched. The incumbent `KATHOOM ALKHOBAR`
image letterhead keeps the default flag, because 1,515 historical Sales Invoices
print through it and changing how they render is the client's decision, not ours.
This record sits beside it and is reached only by the KATC print buttons.

THE FACTS ARE LITERAL, taken from the artefact and NOT derived from
Company/Address. The artefact is the specification: the client redesigned this
stationery, and a letterhead that silently changed because somebody edited an
Address record would be a defect, not a feature.
"""

import frappe
from frappe.utils import cstr

#: The one record this module owns. Every format, test and the button JS reach it
#: through here (or through `print_helpers.yht_katc_lh`) so the name is written
#: down exactly once on the Python side.
KATC_LETTER_HEAD = "KATC Letterhead"

#: Served from `yht_custom/public/images/`. If this file is ever REPLACED the
#: filename must change too — `/assets/` goes out with no `Cache-Control`.
LOGO_URL = "/assets/yht_custom/images/katc_logo.jpg"

#: The wrapper class is load-bearing, not cosmetic. The KATC print formats render
#: `{{ letter_head }}` only when it carries this marker, so a document whose
#: `letter_head` is the incumbent image (or the dangling
#: `Kathoom without letterhead`) cannot smuggle the wrong header onto a KATC
#: layout. See `get_letter_head` precedence in the format templates.
MARKER_CLASS = "katc-lh"

#: Literal facts from the artefact.
COMPANY_EN = "KATHOOM ALKHOBAR TRADING CO."
COMPANY_AR = "شركة كتوم الخبر التجارية"
TAGLINE_EN = "For All Kinds of Pipes &amp; Fittings"
TAGLINE_AR = "بيع جميع أنواع الأنابيب وتركيباتها"
BUILDING_NO = "6603"
POSTAL_CODE = "34429"
ADDITIONAL_NO = "3432"
STREET_EN = "Al Amir Talal Ibn Abdul Aziz"
STREET_AR = "الأمير طلال بن عبد العزيز"
DISTRICT_EN = "Ash Shamalyyah"
DISTRICT_AR = "الشمالية"
CITY_EN = "Al Khobar"
CITY_AR = "الخبر"
CR_NUMBER = "2051226328"
VAT_NUMBER = "311264592800003"
TELEPHONE = "+966 13 8972579 / 8651533"
EMAIL = "sales@kathoomcompany.com"

#: Colours sampled from the artefact.
INK = "#164f82"
RULE = "#17305f"
ACCENT_RED = "#df1f26"

#: The `Print Without LH` spacer, in points. ONE owner for a number seven print
#: formats and the suite have to agree on: the formats reach it through
#: `print_helpers.yht_katc_spacer_pt()`, the tests import it from here.
#:
#: MEASURED off the client's artefacts with `pdftotext -bbox`, not assumed. The
#: without-letterhead print goes onto PRE-PRINTED stationery, so the body has to
#: clear the physical header band the paper already carries — first glyph on the
#: page, one page each:
#:
#:   | pair                       | Print 1 (with LH) | Print 2 (without) | drop |
#:   | DN Print 1 / DN print 2    |            136.02 |            160.02 | 24.0 |
#:   | Invoice Print 1 / 2        |            148.40 |            172.40 | 24.0 |
#:   | SO Print 1 / SO Print 2    |            134.52 |            149.52 | 15.0 |
#:   | quote Print 1 / Print 2    |            138.22 |            149.52 | 11.3 |
#:
#: 🔴 The spec's "fixed-height spacer of 24 pt" is the DROP, not the spacer. At
#: 24 pt the rendered body started at y=44.54 — 115 pt ABOVE `DN print 2` — and
#: 62 pt above our OWN with-letterhead body (y=106.78 after the 42/16/42 fix).
#:
#: 🔴 AND THIS IS A CSS LENGTH, NOT A PAGE POSITION. wkhtmltopdf lays this page
#: out at ≈0.767 PDF pt per CSS pt: measured, raising the spacer from 24 to 154
#: moved the body 99.7 pt, not 130. So "86.2 pt of letterhead + 24 pt = 110 pt"
#: is the wrong arithmetic twice over — re-render, never add up.
#:
#: ONE constant cannot land on four different artefact positions, so it is set to
#: the DEEPEST of them (`Invoice Print 2`, 172.40 pt). Too much clearance is white
#: space; too little prints into the band the paper already carries. Rendered at
#: 194: body at y=173.29 (Tax Invoice) and y=175.35 (Delivery Note, Quotation
#: No LH, Sales Order No LH) — each at or below its own artefact. Re-measure if the
#: letterhead height ever changes; the two are the same band.
NO_LH_SPACER_PT = 194


def _another_letter_head_is_default() -> bool:
	"""Does some OTHER `Letter Head` hold `is_default`?

	🔴 THE GUARD ON `doc.save()`. When the answer is no,
	`LetterHead.validate_disabled_and_default` sets `is_default = 1` on whatever
	is being saved (`letter_head.py:55-57`), and `on_update` then calls
	`set_as_default()`, which clears the flag on EVERY other record and writes the
	global `set_default("letter_head", self.name)` plus
	`default_letter_head_content` (`letter_head.py:118-127`). A following
	`db_set("is_default", 0)` reverses none of that — it only puts one column back.

	This module's central promise is that `KATC Letterhead` never becomes the
	default, so the caller writes the fields with `db_set` instead of saving when
	this returns False.
	"""
	return bool(
		frappe.db.exists(
			"Letter Head", {"is_default": 1, "name": ("!=", KATC_LETTER_HEAD)}
		)
	)


def setup_katc_letterhead() -> dict:
	"""Create or refresh the record. Idempotent, and it must stay that way.

	Runs inside `setup.after_migrate`'s per-step try/except on every deploy.
	Content is compared before saving: frappe normalises HTML on save and inserts
	its own `<tbody>`, so markup written without one comes back 15 bytes longer
	than it went in, the comparison never holds, and every single migrate rewrites
	the record and floods the Version table (gotcha 26). `build_content` writes the
	`<tbody>` by hand for exactly that reason.

	🔴 `source` IS PART OF THE COMPARISON. `LetterHead.before_insert` runs
	`self.source = "Image"` unconditionally ("for better UX, let user set from
	attachment"), AFTER the field values handed to `get_doc` are set — so no insert
	can create an HTML letter head in one call, and the `source` passed below is
	discarded every time. It is put back with `db_set` after the insert, and
	`source` is compared here so that a record already sitting at `Image` (every
	site provisioned before this was fixed) is repaired on the next migrate instead
	of short-circuiting to `unchanged` because the content happens to match.
	"""
	created, updated, unchanged = 0, 0, 0

	content = build_content()
	# The page-number line belongs to each print format's `#footer-html`, which is
	# what wkhtmltopdf is handed as `--footer-html`. A Letter Head footer would
	# render once, in the flow, with the page spans unresolved.
	footer = ""

	if frappe.db.exists("Letter Head", KATC_LETTER_HEAD):
		doc = frappe.get_doc("Letter Head", KATC_LETTER_HEAD)
		if (
			cstr(doc.content) == content
			and cstr(doc.footer) == footer
			and cstr(doc.source) == "HTML"
		):
			unchanged += 1
		elif _another_letter_head_is_default():
			doc.source = "HTML"
			doc.content = content
			doc.footer = footer
			doc.disabled = 0
			doc.flags.ignore_permissions = True
			doc.save()
			# `validate_disabled_and_default` runs on save too — same repair as the
			# insert branch below, for the same reason.
			doc.db_set("is_default", 0, update_modified=False)
			updated += 1
		else:
			# Nothing else holds the flag, so `save()` would hand it to THIS record
			# and `db_set` could not take it back — see
			# `_another_letter_head_is_default`. Write the fields straight to the
			# row instead. `build_content` already emits the `<tbody>` frappe's
			# HTML normalisation would have inserted (gotcha 26), so what is stored
			# here is byte-identical to what a `save()` would have stored, and the
			# comparison above still holds on the next migrate.
			# Keyword arguments on purpose: `log_error(title, message)` writes the
			# FIRST argument into `Error Log.method`, which is 140 characters. A
			# positional long string throws CharacterLengthExceededError from inside
			# the error logger.
			frappe.log_error(
				title="yht_custom: KATC letterhead not saved",
				message=(
					f"{KATC_LETTER_HEAD} was refreshed with db_set instead of save(): "
					"no other Letter Head holds is_default, so "
					"validate_disabled_and_default would have made this one the site "
					"default. Set a default Letter Head."
				),
			)
			doc.db_set("source", "HTML", update_modified=False)
			doc.db_set("content", content, update_modified=False)
			doc.db_set("footer", footer, update_modified=False)
			doc.db_set("disabled", 0, update_modified=False)
			doc.db_set("is_default", 0, update_modified=False)
			updated += 1
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Letter Head",
				"letter_head_name": KATC_LETTER_HEAD,
				"source": "HTML",
				"content": content,
				"footer": footer,
				# Never default. `Company.default_letter_head` is the client's image
				# letterhead and 1,515 invoices print with it.
				"is_default": 0,
				"disabled": 0,
			}
		).insert(ignore_permissions=True)
		# Two framework validations overrule the fields above, and both are put back
		# by hand. `db_set` rather than a second `save()`, because a save re-runs
		# exactly the validations being undone.
		#   - `before_insert` forces `source = "Image"` (see the docstring).
		#   - `validate_disabled_and_default` sets `is_default = 1` when the site has
		#     no other default Letter Head. On THIS site the incumbent
		#     `KATHOOM ALKHOBAR` holds it, so the flag stays 0 — but a fresh site
		#     would silently make the KATC head the default and contradict the
		#     module docstring.
		doc.db_set("source", "HTML", update_modified=False)
		doc.db_set("is_default", 0, update_modified=False)
		created += 1

	return {"created": created, "updated": updated, "unchanged": unchanged}


# ------------------------------------------------------------------- rendering


def build_content() -> str:
	"""The bilingual header markup.

	RTL rule, and the reason the Arabic column reads the way it does: the client's
	own HTML writes `الرمز البريدي: 34429` and `س.ت: 2051226328` — a colon
	immediately before an LTR numeric run inside an RTL block. The bidi algorithm
	relocates that colon to the visual LEFT of the label, so it prints as
	`:الرمز البريدي`. Every colon is dropped from the Arabic side here.

	🔴 AND THE SPANS ARE RATIONED, NOT APPLIED EVERYWHERE. `<span dir="ltr">` goes
	on AT MOST ONE run per Arabic line, and only where the run is not pure digits
	— so the phone (a slash between two numbers) and the e-mail (Latin letters)
	carry one, while the postal/building line and the CR/VAT line carry NONE.
	Two explicitly-directional inline boxes on one RTL line come back from
	wkhtmltopdf 0.12.6 as overlapping runs of glyphs; a bare digit run needs no
	span at all, because bidi already reads European numerals left-to-right inside
	an RTL paragraph. Measured in the PDF, invisible in the browser print view.
	CLAUDE.md gotcha 45 — the comment beside `arabic_details` below repeats it, so
	do not "fix" one without the other.
	"""
	# `dir="ltr"` around a numeric run inside an RTL block: without it the bidi
	# algorithm reorders "+966 13 8972579 / 8651533" around the slash.
	def ltr(value: str) -> str:
		return f'<span dir="ltr">{value}</span>'

	english_details = (
		f"Building No. {BUILDING_NO} - Postal Code {POSTAL_CODE} - Additional No. {ADDITIONAL_NO}<br>"
		f"{STREET_EN} - {DISTRICT_EN} - {CITY_EN}<br>"
		f"C.R. {CR_NUMBER} - VAT No. {VAT_NUMBER}"
	)
	# 🔴 ONE `<span dir="ltr">` PER LINE, AND ONLY WHERE THE RUN IS NOT PURE DIGITS.
	# wkhtmltopdf 0.12.6's WebKit mis-positions a SECOND explicitly-directional inline
	# box inside an RTL line: rendered to PDF, the address line and the CR/VAT line
	# came back as two overlapping runs of glyphs (measured, not guessed — it is
	# invisible in the browser print view and only the PDF shows it). A bare digit run
	# needs no span at all: the bidi algorithm already reads European numerals
	# left-to-right inside an RTL paragraph. Only the phone (a slash between two
	# numbers) and the e-mail (Latin letters) need the wrapper, and they are one per
	# line.
	arabic_details = (
		f"مبنى {BUILDING_NO} - الرمز البريدي {POSTAL_CODE}"
		f" - الرقم الإضافي {ADDITIONAL_NO}<br>"
		f"{STREET_AR} - {DISTRICT_AR} - {CITY_AR}<br>"
		f"س.ت {CR_NUMBER} - الرقم الضريبي {VAT_NUMBER}"
	)

	return f"""<div class="{MARKER_CLASS}">
<style>
.{MARKER_CLASS} {{ font-family: Arial, "Noto Sans", sans-serif; color: {INK}; }}
.{MARKER_CLASS} table.katc-lh-grid {{ width: 100%; border-collapse: collapse; border-bottom: 0.35mm solid {RULE}; }}
.{MARKER_CLASS} table.katc-lh-grid td {{ vertical-align: middle; padding: 0 0 2.5mm; }}
.{MARKER_CLASS} .katc-lh-en {{ width: 42%; text-align: center; line-height: 1.15; }}
.{MARKER_CLASS} .katc-lh-logo {{ width: 16%; text-align: center; }}
.{MARKER_CLASS} .katc-lh-logo img {{ width: 31mm; height: auto; }}
.{MARKER_CLASS} .katc-lh-ar {{ width: 42%; direction: rtl; text-align: center; line-height: 1.18; font-family: Arial, "Noto Naskh Arabic", sans-serif; }}
.{MARKER_CLASS} .katc-lh-co {{ font-family: Georgia, "Times New Roman", serif; font-size: 5.15mm; font-weight: 700; letter-spacing: .18mm; white-space: nowrap; }}
.{MARKER_CLASS} .katc-lh-co-ar {{ font-size: 5mm; font-weight: 700; white-space: nowrap; }}
.{MARKER_CLASS} .katc-lh-tag {{ margin-top: 1.8mm; font-family: Georgia, "Times New Roman", serif; font-size: 2.85mm; font-weight: 700; }}
.{MARKER_CLASS} .katc-lh-tag-ar {{ margin-top: 1.3mm; font-size: 2.75mm; font-weight: 700; }}
.{MARKER_CLASS} .katc-lh-det {{ margin-top: 2.2mm; font-size: 2.35mm; font-weight: 600; line-height: 1.35; }}
.{MARKER_CLASS} .katc-lh-con {{ margin-top: 1.4mm; font-size: 2.35mm; font-weight: 600; white-space: nowrap; }}
.{MARKER_CLASS} .katc-lh-accent {{ width: 100%; border-collapse: collapse; }}
.{MARKER_CLASS} .katc-lh-accent td {{ height: 0.65mm; font-size: 0; line-height: 0; padding: 0; }}
</style>
<table class="katc-lh-grid">
  <tbody><tr>
    <td class="katc-lh-en">
      <div class="katc-lh-co">{COMPANY_EN}</div>
      <div class="katc-lh-tag">{TAGLINE_EN}</div>
      <div class="katc-lh-det">{english_details}</div>
      <div class="katc-lh-con">Tel {TELEPHONE}</div>
      <div class="katc-lh-con">Email {EMAIL}</div>
    </td>
    <td class="katc-lh-logo"><img src="{LOGO_URL}" alt="{COMPANY_EN} logo"></td>
    <td class="katc-lh-ar">
      <div class="katc-lh-co-ar">{COMPANY_AR}</div>
      <div class="katc-lh-tag-ar">{TAGLINE_AR}</div>
      <div class="katc-lh-det">{arabic_details}</div>
      <div class="katc-lh-con">هاتف {ltr(TELEPHONE)}</div>
      <div class="katc-lh-con">البريد الإلكتروني {ltr(EMAIL)}</div>
    </td>
  </tr></tbody>
</table>
<table class="katc-lh-accent">
  <tbody><tr>
    <td style="width: 68%; background: {ACCENT_RED};"></td>
    <td style="width: 32%; background: {RULE};"></td>
  </tr></tbody>
</table>
</div>"""
