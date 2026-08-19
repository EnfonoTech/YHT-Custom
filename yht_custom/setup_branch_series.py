# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Branch-wise document numbering.

The client's own convention is kept: ``KS<ABBREV>-.YY.-.####`` — the existing
``KSIN-``, ``KSDN-``, ``KSPI-`` names already have this shape, so history stays
readable instead of being cut in half by a new scheme.

Counter isolation comes for free: Frappe keys ``tabSeries`` on the fully
resolved prefix, so ``KSIN-26-`` and ``KSPI-26-`` are separate counters. A
prefix WITHOUT the doctype abbreviation would make every doctype share one
counter — which is exactly the trap the legacy site fell into.
"""

import frappe

#: (doctype, abbreviation, supports_return)
SERIES_TARGETS = [
	("Sales Invoice", "IN", True),
	("Delivery Note", "DN", True),
	("Sales Order", "SO", False),
	("Quotation", "SQ", False),
	("Purchase Invoice", "PI", True),
	("Purchase Receipt", "PR", True),
	("Purchase Order", "PO", False),
	("Payment Entry", "PY", False),
	("Journal Entry", "JV", False),
	("Stock Entry", "SE", False),
	("Material Request", "MR", False),
	("Stock Reconciliation", "SR", False),
]

#: Return-variant abbreviations. A credit note is not "a sales invoice, return
#: flavour" to an accountant — it has its own name and needs its own series.
RETURN_SUFFIX_OVERRIDES = {
	"Sales Invoice": "CN",   # Credit Note
	"Delivery Note": "DRN",  # Delivery Return Note
	"Purchase Invoice": "DBN",  # Debit Note
	"Purchase Receipt": "PRN",  # Purchase Return Note
}

TEMPLATE = "{prefix}{abbrev}-.YY.-.####"


def build_template(prefix: str, abbrev: str) -> str:
	return TEMPLATE.format(prefix=prefix, abbrev=abbrev)


def setup_branch_series():
	"""Seed Branch Naming Series rows and the naming_series pickers.

	Idempotent — safe on every ``after_migrate``. Branches with no
	``custom_doc_prefix`` are skipped, so a half-configured Branch cannot
	generate garbage series.
	"""
	branches = frappe.get_all(
		"Branch",
		filters={"custom_doc_prefix": ["not in", ["", None]]},
		fields=["name", "custom_doc_prefix"],
	)
	if not branches:
		return

	# doctype -> ordered list of every branch's templates, for the picker
	options_by_doctype: dict[str, list[str]] = {}

	for branch in branches:
		prefix = (branch.custom_doc_prefix or "").strip()
		if not prefix:
			continue

		wanted = []
		for doctype, abbrev, supports_return in SERIES_TARGETS:
			if not frappe.db.exists("DocType", doctype):
				continue
			wanted.append((doctype, build_template(prefix, abbrev), 0))
			if supports_return:
				ret_abbrev = RETURN_SUFFIX_OVERRIDES.get(doctype, f"{abbrev}R")
				wanted.append((doctype, build_template(prefix, ret_abbrev), 1))

		_sync_branch_rows(branch.name, wanted)

		for doctype, template, _flag in wanted:
			options_by_doctype.setdefault(doctype, [])
			if template not in options_by_doctype[doctype]:
				options_by_doctype[doctype].append(template)

	for doctype, templates in options_by_doctype.items():
		_sync_naming_series_options(doctype, templates)

	frappe.db.commit()


def _sync_branch_rows(branch: str, wanted: list[tuple[str, str, int]]):
	"""Replace the Branch's series child rows with the computed set."""
	doc = frappe.get_doc("Branch", branch)
	if not doc.meta.has_field("custom_naming_series_table"):
		return

	existing = {(r.parent_doctype, r.naming_series, int(r.use_for_return or 0)) for r in doc.custom_naming_series_table}
	if existing == set(wanted):
		return

	doc.custom_naming_series_table = []
	for doctype, template, use_for_return in wanted:
		doc.append(
			"custom_naming_series_table",
			{"parent_doctype": doctype, "naming_series": template, "use_for_return": use_for_return},
		)
	doc.flags.ignore_permissions = True
	doc.flags.ignore_validate_update_after_submit = True
	doc.save()


def _sync_naming_series_options(doctype: str, templates: list[str]):
	"""Put the branch templates into the doctype's naming_series options.

	Frappe validates a saved document's series against this list and renders the
	picker from it, so a template missing here is rejected at insert.
	"""
	meta_field = frappe.get_meta(doctype).get_field("naming_series")
	if not meta_field:
		return

	existing = frappe.db.get_value(
		"Property Setter",
		{"doc_type": doctype, "field_name": "naming_series", "property": "options"},
		["name", "value"],
		as_dict=True,
	)

	standard = [o for o in (meta_field.options or "").split("\n") if o.strip()]
	# PRESERVE what is already there. Rebuilding from `standard + templates` alone
	# silently deletes series other provisioning steps added — that is exactly how
	# the expense series (KSEXP-) kept disappearing, because this function ran
	# after the step that registered it. Union, and keep a stable order:
	# ERPNext's own defaults, then this branch's templates, then anything else.
	previous = [o for o in (existing.value or "").split("\n") if o.strip()] if existing else []
	extras = [o for o in previous if o not in standard and o not in templates]
	merged = list(dict.fromkeys([*standard, *templates, *extras]))
	value = "\n".join(merged)
	if existing:
		if existing.value != value:
			frappe.db.set_value("Property Setter", existing.name, "value", value)
		return

	frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": doctype,
			"field_name": "naming_series",
			"property": "options",
			"property_type": "Text",
			"value": value,
		}
	).insert(ignore_permissions=True)
