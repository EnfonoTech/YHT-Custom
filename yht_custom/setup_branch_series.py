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

🔴 THE RETURN ABBREVIATIONS WERE INVENTED, NOT OBSERVED — corrected 2026-08-26.
The first version chose accountant's names (CN / DRN / DBN / PRN) while claiming
to continue the client's convention. It did not: measured on the live data, the
client's return series are ``KSSR-`` (98 of 102 sales returns), ``KSDR-`` (34 of
38 delivery returns), ``KSPR-`` (56 of 60 purchase-invoice returns) and
``KSPRR-`` (4 of 4 purchase-receipt returns). The invented series had ZERO
documents between them. Every abbreviation below is now one the data shows.

Two live collisions came out of the same mistake and are fixed here:

* **Purchase Receipt was inverted.** Forward was configured ``KSPR-`` — which is
  the PURCHASE INVOICE RETURN prefix, 56 documents, counter ``KSPR-26-`` at 11 —
  and its return was configured ``KSPRN-``, which is the real forward prefix,
  534 documents. A receipt and a purchase-invoice return were drawing from one
  counter.
* **Stock Reconciliation was configured on ``KSSR-``**, the sales-return prefix.
  Latent only because all 44 reconciliations still sit on ERPNext's stock
  ``MAT-RECO-``, but the first one created would have taken ``KSSR-26-0031`` out
  of the sales-return counter. It moves to ``RC``.
"""

import frappe

#: (doctype, abbreviation, supports_return)
SERIES_TARGETS = [
	("Sales Invoice", "IN", True),
	("Delivery Note", "DN", True),
	("Sales Order", "SO", False),
	("Quotation", "SQ", False),
	("Purchase Invoice", "PI", True),
	# PRN, not PR: KSPR- belongs to the purchase-invoice RETURN (56 documents).
	("Purchase Receipt", "PRN", True),
	("Purchase Order", "PO", False),
	("Payment Entry", "PY", False),
	("Journal Entry", "JV", False),
	("Stock Entry", "SE", False),
	("Material Request", "MR", False),
	# RC, not SR: KSSR- belongs to the sales RETURN (98 documents).
	("Stock Reconciliation", "RC", False),
]

#: Return-variant abbreviations, every one taken from the names the client is
#: already using. A return is not "an invoice, return flavour" to an accountant —
#: it has its own name and needs its own counter.
RETURN_SUFFIX_OVERRIDES = {
	"Sales Invoice": "SR",  # KSSR- — Sales Return, 98 documents
	"Delivery Note": "DR",  # KSDR- — Delivery Return, 34 documents
	"Purchase Invoice": "PR",  # KSPR- — Purchase Return, 56 documents
	"Purchase Receipt": "PRR",  # KSPRR- — Purchase Receipt Return, 4 documents
}

#: Series this app configured, that the client never used, and that must not stay
#: in a picker. Leaving them there offers an operator a counter with no history
#: behind it; `_sync_naming_series_options` unions rather than replaces, so
#: without this list they would survive every migrate.
RETIRED_SERIES = {
	"Sales Invoice": ["KSCN-.YY.-.####"],
	"Delivery Note": ["KSDRN-.YY.-.####"],
	# `_TEST-KEEPME-` is not a wrong series, it is TEST DEBRIS: an older version of
	# test_existing_entries_survive_a_reseed appended it and called frappe.db.commit(),
	# which tearDown's rollback could not undo, so it became a permanent choosable
	# entry in the live picker on every site the suite had run against.
	"Purchase Invoice": ["KSDBN-.YY.-.####", "KSEXP-.YY.-.####", "_TEST-KEEPME-.YY.-.####"],
	"Purchase Receipt": ["KSPR-.YY.-.####", "KSPRN-.YY.-.####"],
	"Stock Reconciliation": ["KSSR-.YY.-.####"],
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
	# ...but a retired series is dropped even though it was "already there". The
	# union above is what keeps a series alive across migrates, so this is the only
	# place a wrong one can be taken back out. Never drop a template this branch
	# actively wants — a doctype can be both retired-from and retargeted-to
	# (Purchase Receipt gives up KSPR- and keeps KSPRN- as its forward series).
	retired = set(RETIRED_SERIES.get(doctype, [])) - set(templates)
	merged = [o for o in merged if o not in retired]
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
