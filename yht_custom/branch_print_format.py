# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Row 36 (meeting 2026-10-11) — a default print format per branch.

Saeed (1:16:41–1:18:14): the printer icon opens the site's default format, and a
branch should open ITS own — "define the print format in Branch Configuration, then
it applies for that branch's users". Osaid confirmed: "keep the print format default".

## How the printer icon decides, and the one lever that is per-user

`frappe/printing/page/print/print.js::set_default_print_format` fills the format
selector from `this.frm.meta.default_print_format`, and `meta` is the browser's own
copy of the DocType (`locals.DocType[...]`). The SERVER's `meta.default_print_format`
is cached once for everybody — it is the site default and cannot differ by user — but
the browser's copy is per session. So the mechanism is:

* `Branch Configuration` carries a table of (document type → print format);
* `boot_session` resolves the logged-in user's rows into `frappe.boot.
  yht_branch_print_formats`;
* `public/js/branch_print_format.js` sets `frm.meta.default_print_format` from it when
  a form is set up.

The site-wide `default_print_format` Property Setters are NOT touched — those are the
client's own (gotcha 122) — and a direct `/printview?format=` URL, an email attachment
or the toolbar's explicit `format=` buttons are unaffected: only the printer icon's
preselection moves.

A user on two branches gets the first Branch Configuration (by name) that names the
document type. A row naming a disabled or missing format, or a format built for a
different DocType, is refused on save and ignored at boot.

Behind `oct11_r36_branch_print_format`: with it off `boot_value()` is `{}`, so the JS
does nothing and the table is merely stored.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr

from yht_custom import features

FEATURE = "oct11_r36_branch_print_format"


def validate_rows(doc) -> None:
	"""`BranchConfiguration.validate` — every row must name a usable format."""
	seen = set()
	for row in doc.get("print_format") or []:
		document_type = cstr(row.document_type).strip()
		name = cstr(row.print_format).strip()
		if not document_type or not name:
			continue
		if document_type in seen:
			frappe.throw(
				_("Row {0}: {1} is listed twice — one default print format per document type.").format(
					row.idx, document_type
				)
			)
		seen.add(document_type)

		info = frappe.db.get_value(
			"Print Format", name, ["doc_type", "disabled"], as_dict=True
		)
		if not info:
			frappe.throw(_("Row {0}: Print Format {1} does not exist.").format(row.idx, name))
		if cint(info.disabled):
			frappe.throw(_("Row {0}: Print Format {1} is disabled.").format(row.idx, name))
		if info.doc_type != document_type:
			frappe.throw(
				_("Row {0}: Print Format {1} is built for {2}, not {3}.").format(
					row.idx, name, info.doc_type, document_type
				)
			)


def formats_for_user(user: str | None = None) -> dict:
	"""`{document_type: print_format}` for the user's branch(es)."""
	user = user or frappe.session.user
	if not user or user in ("Guest", "Administrator"):
		return {}
	if not frappe.db.table_exists("Branch Configuration Print Format"):
		return {}

	configs = frappe.get_all("Branch Configuration User", filters={"user": user}, pluck="parent")
	if not configs:
		return {}

	rows = frappe.get_all(
		"Branch Configuration Print Format",
		filters={"parent": ["in", configs], "parenttype": "Branch Configuration"},
		fields=["parent", "document_type", "print_format", "idx"],
		order_by="parent asc, idx asc",
	)
	out = {}
	for row in rows:
		if row.document_type in out:
			continue
		info = frappe.db.get_value("Print Format", row.print_format, ["doc_type", "disabled"], as_dict=True)
		if not info or cint(info.disabled) or info.doc_type != row.document_type:
			continue
		out[row.document_type] = row.print_format
	return out


def boot_value() -> dict:
	"""What `boot_session` puts in `frappe.boot.yht_branch_print_formats`."""
	if not features.enabled(FEATURE):
		return {}
	try:
		return formats_for_user()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "YHT boot: branch print formats")
		return {}
