# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Row 29 (meeting 2026-10-11) — a Purchase Order button on the branch dashboard,
open to every branch user.

## What changes

1. **Permission.** `Branch User` and `Branch Manager` get read · write · create ·
   print · email · report on Purchase Order. They do NOT get submit, cancel, amend or
   delete: a branch raises the order, purchasing approves it. That is a decision the
   client has not yet been asked about in words — "allow its access to all users" says
   *access*, not *approve* — so it is the conservative reading, and `SUBMIT_RIGHT` is
   the one line to flip. (Purchase Manager / Purchase User on this site already hold
   submit.)
2. **Scope.** The row filter. Before this, `Branch User` already held **read** on
   Purchase Order (for the report tiles) and `permission_query_conditions` had NO entry
   for it — so a branch user's list showed every branch's purchase orders. That was
   latent while the role could only read through reports; with create rights it would
   be a plain leak, so the filter ships in the same switch as the permission.
3. **The tile** on `yht-dashboard` and its destination in `branch_user_restrict.js`
   (gotcha 7: a tile and an allow-list entry, or the user bounces straight back).

## What already protects a branch user's write

`doc_events` for Purchase Order already carries `_BRANCH_DEFAULT_EVENTS` — the branch
cost-centre override, the naming-series pick, and `branch_guard.validate_branch_scope`,
which rejects any warehouse or cost centre outside the user's branch on `validate`.
That is the real boundary (CLAUDE.md, "The five permission layers"); the filter above
is list hygiene, not the lock.

Behind `oct11_r29_branch_purchase_order`: with it off, `purchase_order_query` returns
`""` (today's behaviour, including the unfiltered read) and no permission row is written.
"""

import frappe

from yht_custom import features

FEATURE = "oct11_r29_branch_purchase_order"

#: Flip to 1 if purchasing wants branches to approve their own orders.
SUBMIT_RIGHT = 0

PURCHASE_ORDER_PERMISSION = {
	"parent": "Purchase Order",
	"read": 1,
	"write": 1,
	"create": 1,
	"print": 1,
	"email": 1,
	"report": 1,
	"submit": SUBMIT_RIGHT,
}


def purchase_order_query(user):
	"""`permission_query_conditions` for Purchase Order — branch scope, behind the switch."""
	if not features.enabled(FEATURE):
		return ""
	from yht_custom.branch_filters import _warehouse_or_owner

	return _warehouse_or_owner("Purchase Order", ["set_warehouse"], "Purchase Order Item", user)


def setup_branch_purchase_order() -> dict:
	"""Grant the two branch roles their Purchase Order rights. Idempotent."""
	if not features.enabled(FEATURE):
		return {"skipped": f"{FEATURE} is off for this site"}
	if not frappe.db.exists("DocType", "Purchase Order"):
		return {}

	from yht_custom.setup import BRANCH_MANAGER_ROLE, BRANCH_USER_ROLE, _upsert_custom_docperm

	for role in (BRANCH_USER_ROLE, BRANCH_MANAGER_ROLE):
		_upsert_custom_docperm("Purchase Order", role, PURCHASE_ORDER_PERMISSION)
	frappe.clear_cache(doctype="Purchase Order")
	return {"roles": [BRANCH_USER_ROLE, BRANCH_MANAGER_ROLE], "submit": SUBMIT_RIGHT}
