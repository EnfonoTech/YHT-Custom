# Handoff — the remaining 2026-09-23 change requests, on UAT

**Date:** 2026-09-26
**Branch:** `meeting-0923-remaining` (not yet merged to `main`)
**Deployed to:** `yht-test` only. `yht-khobhar.enfonoerp.com` is unchanged and was proved so.
**Bench:** `/home/v15/yht-bench` on EFTSP-013 (`144.91.82.218`, via control `194.163.160.83`)

---

## The constraint that shaped everything

`yht-khobhar.enfonoerp.com` (live) and `yht-test` (UAT) are two sites on **one bench**,
sharing **one `apps/yht_custom`**. A template is read from disk on every render and a
`doc_events` handler is registered once for both sites. So "deploy to UAT first" is not
something the filesystem can express here — the code is live on production the moment it
is pulled.

`yht_custom/features.py` is the answer. Every behaviour change in this batch reads a
switch out of the SITE's own `site_config.json`:

```json
"yht_features": ["all"]
```

`yht-test` has it. `yht-khobhar.enfonoerp.com` does not, and with the key absent every
switch reads false.

**Promoting to production is a config change plus a migrate. It is not a code push.**

### Proof that production did not move

A print of the latest submitted document in each of six formats was rendered and hashed
**before** the branch was pulled, and again after. All six are byte-for-byte identical:

| Format | Before | After |
|---|---|---|
| KATC Quotation | `a73231422396a523` | identical |
| KATC Quotation Arabic | `f2f7a3c8ff11b83a` | identical |
| KATC Quotation Proforma | `2cf7f606fecd831e` | identical |
| KATC Sales Order | `4348b931f5d236c4` | identical |
| KATC Tax Invoice | `831aa7bacf271fdc` | identical |
| KATC Delivery Note | `f6589646c349e3f0` | identical |

That check earned its keep: the first deploy DID change two of them. `&rlm;` renders the
same as U+200F and `{%- if %}` swallowed a newline, so the output was equivalent and the
bytes were not. Equivalent is an assumption until something renders it.

---

## What the work actually found

Three CRs turned out to be about something other than what they said.

### CR-002 — the premise was backwards

The CR asks to "remap district to `county`". That would break the e-invoice.
`ksa_compliance` hardcodes `custom_area` as `buyer_district` in
`sales_invoice_additional_fields._set_buyer_address`, and the client's own SPL paste
parser assigns `parts[3]` — the district — to that same field. So `custom_area` is
authoritative and `county` is the legacy column to recover **from**.

630 addresses: 630 have a city, 340 a county, 19 a `custom_area`. The county is dirty —
genuine districts, the city repeated, city+district run together, street names, and the
literal string `"NULL"` on three rows. `address_district.classify()` sorts each value and
only a genuine district is copied. On UAT: **241 recovered, 72 city-only, 3 junk, 3
street** left as a cleanup list for the client.

### CR-005 — there was nothing to build

`select_print_heading` is a **standard ERPNext field**, present on all six doctypes and
already `allow_on_submit = 1`, which is exactly what makes a field bulk-editable from the
list view. The client is already using it: 1,906 of 1,964 Delivery Notes, 2,369 of 3,614
Purchase Invoices, 1,108 of 2,481 Sales Invoices carry one.

**The prints ignored it and hardcoded their titles.** That was the whole defect.

### CR-012 — the flag was never the mechanism

`custom_is_expense_invoice` was `0` on **all 3,614** Purchase Invoices while **384**
carried a `KSEPI-` / `EPI-` series, the most recent created 2026-08-31. Operators pick the
series out of the naming-series dropdown and never see the checkbox — so `update_stock = 0`,
the expense-head stamping and the stock-item guard have **never once run in production**.

And a Property Setter had set `in_standard_filter = 0` on the flag, so it was not even
filterable — which is why "correct them in bulk" had nowhere to start.

### CR-003 — a live defect, not a layout preference

A `custom_more_details` Tab Break had been added to Address through Customize Form by the
other developer. The stored field order put it after `links`, which left **`pincode`,
`city`, `country` and `address_type` on the second tab** — and `pincode`,
`custom_short_address` and `custom_additional_number` all carry a `reqd` Property Setter on
this site. An operator filling the first tab and saving was told a required field was empty
on a tab they had no reason to open.

---

## What UAT caught that review did not

Every one of these survived writing and reading the code, and died on the first deploy.

1. **`["in", ["", None]]` does not match NULL.** SQL's `IN` compares with `=`, and
   `x = NULL` is NULL. The print-heading backfill filled 18 rows out of thousands and
   reported success. `["is", "not set"]` is the frappe filter that becomes `ifnull(f,'')=''`.
   After the fix: **11,253**.
2. **Patches run before `after_migrate`.** The fields and Print Heading records the
   backfill writes into are created there, so on a first migrate it had nothing to write
   into and said so by omitting its own result key. Both provisioning steps are idempotent
   and are now called from the patch itself.
3. **A stored heading outranked the template printing the document.** The backfill stamped
   "Sales Quotation" onto 2,726 quotations, and every Proforma print then said QUOTATION.
   The template naming itself is the more specific statement.
4. **`_read_order` seeds standard fields only** — deliberately, so a pairwise move cannot
   fight `insert_after`. A *declared* order is the opposite case, and against that base all
   thirteen Address custom fields reported absent and nothing moved. Twice, including after
   the Tab Break had been created. It bases on live meta now.
5. **Two ordering mechanisms on one doctype.** The declared order put District between
   Address Line 2 and Postal Code; the pairwise pass then hoisted Postal Code · City ·
   Country back above it, every migrate. A test asserts the two dicts never name the same
   doctype.
6. **`city` is dirty too.** Address `CU0341-Billing` carries county "Dammam" and city
   " Industrial City", so the row-local comparison stored Dammam as a district.
   `recheck()` released 19 such values and kept 222.

---

## What is on UAT, per CR

| CR | State | Note |
|---|---|---|
| CR-001 | done | Both Client Scripts ported to `public/js/address.js`; originals auto-disabled where the switch is on |
| CR-002 | done | 241 districts recovered; 78 left as a client cleanup list |
| CR-003 | done | First tab = Short Address · Type · Building No · Street · Additional No \| District · Postal · City · Country |
| CR-004 | done | Heading, language and letterhead all chosen at print time |
| CR-005 | done | 11,253 documents backfilled; field in the list sidebar |
| CR-006 | done | Warehouse fixed from Branch Configuration; the branch's own warehouses are left alone |
| CR-007 | done | SO Customer PO moved up; DN declared; Quotation reordered |
| CR-008 | done | 1,800 of 1,831 notes carry their SO / SI numbers |
| CR-009 | **partial** | Name works. Mobile: **1 of 26** Sales Persons has one. Data, not code |
| CR-012 | done | Flag derived from the series; 897 backfilled on UAT; standard filter restored |
| CR-013 | done, **switched off** | Built for DN + SI. OQ-9 unanswered, so production is untouched until the client names the lists |
| CR-014 | done, **needs the number** | Field created; letterhead unchanged until it is filled |
| CR-015 | done | The one Other Remarks box, on the front page |
| CR-020 | done | Stock · Sales Statements · Receivables & Collection · Ledgers · Purchase · Data & Go-Live |
| CR-021 | done | `KATC Purchase Order`, a sibling of the Sales Order format |
| CR-018 | done | **OQ-6 answered.** The ask is the SEARCH POPUP under the Item Code cell, not the column — see below |
| CR-019 | done | **OQ-7 answered.** A DOUBLE click on the Rate cell was opening the dialog — see below |

---

### CR-018 was not what it was written down as

The CR says "item description column: widen, but narrow specifically during
search/query", and it was recorded as blocked because nobody could work out which
UI moment "when querying" meant. The client's screenshot settles it: it is the
**awesomplete popup** that opens under the Item Code cell while you type, not the
grid column at all.

**And the column is not what sizes that popup.**
`frappe/public/scss/common/awesomeplete.scss` gives
`.awesomplete > [role="listbox"]` `width: 100%` **and** `min-width: 250px`, so it
is 250px wide on every grid cell narrower than that. Widening the Item Code
column — the change the CR as written asked for — would have moved nothing.

520px, sized on the data: measured across every Item on `yht-khobhar`, `item_name`
is 41 characters at the median, 54 at p90, 63 at p99, 75 at its longest, and 1,119
items are over 45. `Item.search_fields` is
`item_name,description,item_group,customer_code`, so four values stack in every
row — the description still wraps, which is the point of the request.

Desktop only: `grid.scss` sets `.form-grid-container { overflow-x: clip }` below
the `md` breakpoint and `overflow-x: unset !important` above it, so on a phone a
520px popup would be cut off by the container rather than overflow it. Falling off
the right edge is already handled upstream — `link.js` measures the dropdown
against the viewport on every open and flips it to `.awesomplete-align-right`.

A stylesheet cannot read `site_config.json`, so the rule is scoped to
`body.yht-wide-grid-search` and `public/js/grid_search_width.js` writes that class
from the boot payload — on `app_ready`, because `frappe.boot` is empty when a desk
bundle first evaluates.

### CR-019 was not two UI paths either

The CR describes "two ways to change a line's rate… clicking the rate cell
directly, and a separate button", and it was blocked because nobody could find a
click handler on the Rate cell. There isn't one. The meeting recording shows the
actual gesture, and my own first reading of it — Rate cell versus Price Assist
button, with the fix being `rate_lock.js` made read-only for every row — was
**wrong**, and would have taken away the only way to price a hand-added line.

What is really there is at `public/js/price_assist.js`, under BUTTON PLACEMENT: a
**capture-phase listener on `document`** that opens the Price Assist dialog on a
**DOUBLE click** of any grid `[data-fieldname="rate"]` cell, within 600 ms.

**A double click on a number is how anybody selects it to retype it.** An operator
reaching for a 190.00 to change it gets a modal, and has to dismiss it before
typing. That is the whole complaint, and "keep only the button" is exactly the
right instruction.

Removed, behind `cr_019_no_rate_doubleclick`. Untouched: the `Price Assist` and
`Show Price History` footer buttons, and the quiet inline hint on `rate` — a
`frappe.show_alert` toast that warns when the rate is off the last rate to that
customer, which blocks nothing.

⚠️ The feature check runs BEFORE the handler's `closest()` call, deliberately.
That listener fires on **every click in the desk**; with the switch on it now does
strictly less work per click than it did before.

## Promoting to production

1. Merge `meeting-0923-remaining` into `main`.
2. On the box: `cd /home/v15/yht-bench/apps/yht_custom && git checkout main && git pull`
   — **the remote is called `upstream`, not `origin`, and its fetch refspec is pinned to
   `main`.** `git fetch origin` exits non-zero and a careless script will still print
   "deployed".
3. Add `"yht_features": ["all"]` to
   `sites/yht-khobhar.enfonoerp.com/site_config.json` — or name individual switches to
   promote them one at a time. **Never put this key in `common_site_config.json`.**
4. `bench --site yht-khobhar.enfonoerp.com migrate`
5. `supervisorctl restart yht-bench-web: yht-bench-workers:` — new jinja methods are
   resolved when the environment is built, so an un-reloaded worker 500s every website
   page including `/login`.
6. Re-run the print hash check. With the switches ON the hashes are *expected* to move;
   what matters is that the titles are the intended ones.

### Carried over, unchanged

1,607 failed Repost Item Valuation rows are still parked for finance. Root cause is a
deleted Accounting Period; restarting them widens the gap. Four questions for finance are
in the previous handoff.

### Coordination

`saheedkn@gmail.com` builds print formats and edits Property Setters directly on the
production site. This batch now owns three Address fields that were theirs by hand
(`custom_more_details`, `custom_national_address_full_data`, `custom_column_break_mcjwv`)
and disables their two Address Client Scripts wherever the port is switched on. Tell them
before production is promoted.
