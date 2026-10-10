# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Rows 7 + 14 of the 2026-10-08 sheet — the Item picker.

Two complaints, one query:

* **Row 7 — "items not sorted".** ERPNext's `item_query` orders by `idx desc`
  ahead of the name, and `Item.idx` on this site is a leftover from the previous
  system: 1,422 of 4,047 items carry idx 1 and the rest run up to 6,058 — the
  `BI0204…` elbows have 1/4" at 37 and 1" at 48, so 1" lists first. Setting
  `Item.sort_field`, which the client's admin did on live on 2026-10-07, changes
  nothing: the picker never reads it. The codes already encode size in order
  (`…008JP` 1/4" · `…012JP` 3/8" · `…015JP` 1/2" · `…020JP` 3/4" · `…025JP` 1"),
  so ordering by item code IS ordering by size.
* **Row 14 — "search by any words".** Upstream matches the whole typed string
  as one `LIKE '%txt%'`, so `elbow 90 1` finds nothing. Here every word must
  match somewhere in the code, the name or the description, in any order.

🔴 HOW A CALL GETS HERE — two levers, and the first one was believed to be
enough. ERPNext's own JS names `erpnext.controllers.queries.item_query` on the
item grid of every transaction, so a `standard_queries` hook would never be
consulted. `hooks.override_whitelisted_methods` maps that name here, but frappe
15.118 honours that hook only in `handler.execute_cmd`, `api/v2`, `model/mapper`
and `desk/treeview` — `desk/search.py`, the picker's path, resolves the name
with a bare `frappe.get_attr`. Measured on yht-test 2026-10-10: with the hook
registered, "elbow 1" through `search_link` still returned 0 rows. So
`public/js/item_search.js` rewrites the query name inside
`ControlLink.set_custom_query`, and the hook stays for direct API calls.
Until `oct08_r07_item_search` is on for the site both levers call straight
through to ERPNext, so the live site keeps upstream behaviour.

Kept from upstream on purpose, because callers rely on it: the `filters`
contract (Party Specific Item rules, `fcond` / `mcond`, `has_variants = 0`,
disabled, end of life), the display columns — including whatever the site has
put in `Item.search_fields` — and the signature, `as_dict` included.
"""

import json

import frappe
from frappe import scrub
from frappe.desk.reportview import get_filters_cond, get_match_cond
from frappe.utils import cstr, nowdate

from erpnext.controllers.queries import item_query as erpnext_item_query

from yht_custom import features

FEATURE = "oct08_r07_item_search"

#: The columns every typed word is tried against. Barcodes are not searched —
#: this site has 0 `Item Barcode` rows — and `item_group` is not, because a word
#: like "pipe" matching the GROUP of every pipe fitting is exactly the noise the
#: client is complaining about.
WORD_COLUMNS = ("tabItem.name", "tabItem.item_name", "tabItem.description")

#: More words than this is not a search, it is a sentence; the extra ones are
#: ignored rather than compiled into an ever-longer WHERE.
MAX_WORDS = 8


def search_words(txt) -> list[str]:
	"""The words a search must satisfy, in the order typed, empties dropped."""
	return [w for w in cstr(txt).split() if w][:MAX_WORDS]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def item_query(doctype, txt, searchfield, start, page_len, filters, as_dict=False):
	if not features.enabled(FEATURE):
		return erpnext_item_query(doctype, txt, searchfield, start, page_len, filters, as_dict=as_dict)

	doctype = "Item"
	conditions = []

	if isinstance(filters, str):
		filters = json.loads(filters)

	# Display columns — identical to upstream, so the dropdown looks the same and
	# the site's own `search_fields` (last purchase rate, for one) still show.
	meta = frappe.get_meta(doctype, cached=True)
	searchfields = meta.get_search_fields()

	columns = ""
	extra_searchfields = [field for field in searchfields if field not in ["name", "description"]]
	if extra_searchfields:
		columns += ", " + ", ".join(extra_searchfields)
	if "description" in searchfields:
		columns += """, if(length(tabItem.description) > 40, \
			concat(substr(tabItem.description, 1, 40), "..."), description) as description"""

	# Upstream's Party Specific Item handling, verbatim — it rewrites `filters`.
	if filters and isinstance(filters, dict):
		if filters.get("customer") or filters.get("supplier"):
			party = filters.get("customer") or filters.get("supplier")
			item_rules_list = frappe.get_all(
				"Party Specific Item",
				filters={"party": party},
				fields=["restrict_based_on", "based_on_value"],
			)

			filters_dict = {}
			for rule in item_rules_list:
				if rule["restrict_based_on"] == "Item":
					rule["restrict_based_on"] = "name"
				filters_dict[rule.restrict_based_on] = []

			for rule in item_rules_list:
				filters_dict[rule.restrict_based_on].append(rule.based_on_value)

			for filter in filters_dict:
				filters[scrub(filter)] = ["in", filters_dict[filter]]

			if filters.get("customer"):
				del filters["customer"]
			else:
				del filters["supplier"]
		else:
			filters.pop("customer", None)
			filters.pop("supplier", None)

	# Every word, anywhere, any order — this is row 14.
	words = search_words(txt)
	values = {"today": nowdate(), "start": start, "page_len": page_len}
	match_columns = list(WORD_COLUMNS)
	if searchfield and searchfield not in ("name", "item_name", "description") and meta.get_field(searchfield):
		match_columns.append(f"tabItem.{searchfield}")

	word_conditions = []
	for i, word in enumerate(words):
		key = f"w{i}"
		values[key] = f"%{word}%"
		word_conditions.append("(" + " or ".join(f"{col} like %({key})s" for col in match_columns) + ")")
	scond = " and ".join(word_conditions) if word_conditions else "1=1"

	# Ordering — this is row 7. Codes that START with the first word come first
	# (typing a code prefix must find that code at the top), then item code
	# ascending, which on this site is size ascending. `idx` is not consulted.
	values["_first"] = words[0] if words else ""

	return frappe.db.sql(
		"""select
			tabItem.name {columns}
		from tabItem
		where tabItem.docstatus < 2
			and tabItem.disabled=0
			and tabItem.has_variants=0
			and (tabItem.end_of_life > %(today)s or ifnull(tabItem.end_of_life, '0000-00-00')='0000-00-00')
			and ({scond})
			{fcond} {mcond}
		order by
			if(%(_first)s != '' and locate(%(_first)s, tabItem.name) = 1, 0, 1),
			tabItem.name asc
		limit %(start)s, %(page_len)s """.format(
			columns=columns,
			scond=scond,
			fcond=get_filters_cond(doctype, filters, conditions).replace("%", "%%"),
			mcond=get_match_cond(doctype).replace("%", "%%"),
		),
		values,
		as_dict=as_dict,
	)
