# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Row 28 (meeting 2026-10-11) — the buyer's Additional Number reaches ZATCA.

## What was wrong

`ksa_compliance` (lavaloon-eg, 24968b4) writes the literal sentence

    self.buyer_additional_number = 'not available for now'

for EVERY invoice in `SalesInvoiceAdditionalFields._set_buyer_address`, and
`templates/e_invoice.xml` then emits it as `<cbc:PlotIdentification>` whenever it is
non-empty. The customer's Address already carries the real value —
`custom_additional_number`, filled on 161 of this site's addresses (132 customers) —
and nothing ever reads it. Osaid showed it on screen (50:53); Sayanth said it is not
mandatory; the client re-escalated it in the group anyway.

## Why an override and not a doc_event

The tempting fix is a `before_insert` handler on `Sales Invoice Additional Fields`.
It would be WRONG: the controller's own `before_insert` calls `_set_buyer_details`
and then `_prepare_for_zatca`, which builds the invoice XML, hash and QR from the
fields as they stand. A handler registered through `doc_events` runs AFTER the
controller method, so it would rewrite the field after the signed XML had already
been produced from the placeholder — a document whose stored field disagrees with
its own XML. The value has to be right at the moment `_set_buyer_address` assigns it,
which is exactly the method this overrides. Same family as gotcha 120: decide a thing
at the point the data is made, not downstream of it.

## What is sent

* 4 digits (the Saudi National Address format) → sent as is.
* anything else, or blank → **empty**, and the template omits the element. A numeric
  field carrying a sentence is the worse of the two outcomes.

Behind `oct11_r28_zatca_additional_number`: with it off the upstream behaviour runs
unchanged, so the class swap is inert on a site that has not asked for it.
"""

import frappe
from frappe.utils import cstr

from yht_custom import features

FEATURE = "oct11_r28_zatca_additional_number"


def additional_number(address) -> str:
	"""The Address's Additional Number if it is a 4-digit value, else `""`."""
	try:
		raw = address.get("custom_additional_number")
	except Exception:
		return ""
	value = cstr(raw).strip()
	return value if len(value) == 4 and value.isdigit() else ""


def _base_class():
	from ksa_compliance.ksa_compliance.doctype.sales_invoice_additional_fields.sales_invoice_additional_fields import (
		SalesInvoiceAdditionalFields,
	)

	return SalesInvoiceAdditionalFields


def _build():
	base = _base_class()

	class YHTSalesInvoiceAdditionalFields(base):
		def _set_buyer_address(self, address, validate: bool = False):
			super()._set_buyer_address(address, validate)
			if features.enabled(FEATURE):
				self.buyer_additional_number = additional_number(address)

	return YHTSalesInvoiceAdditionalFields


# `override_doctype_class` wants an importable attribute, and the base class lives in
# another app that may not be installed (the test bench for another client). Resolve
# lazily and fall back to the module-level name only when the base imports.
try:
	YHTSalesInvoiceAdditionalFields = _build()
except ImportError:  # pragma: no cover - ksa_compliance not installed
	YHTSalesInvoiceAdditionalFields = None
