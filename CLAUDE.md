# YHT Custom — Agent Context

> Everything an agent needs to continue this app. Read it before touching anything.

## What this is

Frappe/ERPNext **v15** custom app for **Kathoom Alkhobar Trading Co. (KATC)** — the YHT Trading
re-implementation. Multi-branch trading in Saudi Arabia, ZATCA Phase 2 in scope.

**One company per site.** This site carries KATC only, with the **Khobar branch** only. The other group
entities (Jeddah, Jubail, Yanbu, Al Badr, Waqt Al Enjaz) get their own sites — they are not branches here. The
branch machinery is still built in full so adding branch #2 is a configuration change, not a rebuild.

## Environment

| | |
|---|---|
| Site | `yht-khobhar.enfonoerp.com` |
| Server | EFTSP-013 — `144.91.82.218` (ex-ALMashreq, Contabo EU) |
| Bench | **`/home/v15/yht-bench`** — bench user `v15` |
| Server-manager id | `efaa167b-8526-4fec-8912-7b2d4ad231c0` |
| Apps | frappe 15.118.0 · erpnext 15.119.2 · ksa_compliance 0.61.4 · arabic_translation 0.0.1 · hrms 15.63.2 |
| Company | `KATHOOM ALKHOBAR TRADING CO.` (`KATC`), SAR, VAT `311264592800003` |
| Branch | `Kathoom Alkhobar`, prefix `KS` |

### ⚠️ Two benches on one box

`/home/v15/frappe-bench` on the same server runs **live client sites** — almashreq, elco, yas-logistics,
designer-stom. **Every command must name `/home/v15/yht-bench`.** A bench command from the wrong directory hits
those sites.

They are otherwise fully isolated: supervisor group `yht-bench-*` (not `frappe-bench-*`), gunicorn `8001` (not
`8000`), socketio `9001`, own redis. So restarting or migrating yht-bench cannot take a live site down — only
MariaDB and box CPU/RAM are shared.

- Restart with `sudo supervisorctl signal QUIT yht-bench-web:yht-bench-frappe-web` — **never `restart`**, and
  never signal a `frappe-bench-*` program.
- SSL is a **Caddy wildcard block on the control server**. Never run certbot on this box for this site, even
  though the server record says `sslMode: certbot` (that governs the *other* bench).
- `bench` is at `/usr/local/bin/bench`, not in the bench venv.
- Maintenance window is 02:00–05:00 IST as policy. With no live co-tenants on this bench, out-of-window work is
  low risk but still needs **explicit authorisation**, recorded in `~/.claude/skills/enfono-servers/LIVE_STATE.md`.

## Architecture

### Files

| File | Purpose |
|---|---|
| `hooks.py` | app config: `boot_session`, `role_home_page`, `permission_query_conditions`, `doc_events` (12 named doctypes, **not** `*`), fixtures, `after_migrate` |
| `setup.py` | `after_migrate`: Branch User role, Branch custom fields, standard-DocPerm preservation, Branch User DocPerms, Module Profile, series seeding |
| `boot.py` | `boot_session` — pins restricted users to `yht-dashboard`, trims modules/workspaces, forces their own default company |
| `branch_filters.py` | `permission_query_conditions` per doctype, keyed on branch warehouses |
| `branch_defaults.py` | `before_validate` cost-center override + `before_insert` naming-series pick |
| `setup_branch_series.py` | `SERIES_TARGETS` → Branch Naming Series rows + `naming_series` Property Setters |
| `branch_fields.py` | **metadata-derived** list of branch-scoped warehouse / cost-center link fields — the single source of truth shared by the setters and the guard |
| `branch_guard.py` | server-side `validate` scope enforcement — the boundary that makes the Property Setters safe |
| `setup_property_setters.py` | `ignore_user_permissions` on every scoped field |
| `item_naming.py` | item-group-wise item code generation (`Item.before_insert`) |
| `api/dashboard.py` | `get_dashboard_data` for the dashboard page |
| `api/party.py` | simple Customer / Supplier creation — party + address + contact in one call |
| `report_scope.py` | branch scoping for **reports**; `permission_query_conditions` does not reach a Script Report |
| `yht_custom/report/` | Stock Sales · Collection · Branch Receivables (Script Reports) |
| `discount_totals.py` | consolidated item-wise discount, and the grid column that makes it enterable |
| `saudi_address.py` | Saudi national address, Short Code as the address title, `national_address_gaps()` |
| `letterhead.py` | bilingual per-branch Letter Head, generated from live data |
| `hr_setup.py` | GOSI components, Saudi leave types, holiday list, payroll period, `hr_gaps()` |
| `import_gate.py` | the go-live gate (11 checks) + pre/post stock snapshots — plan 7.1 |
| `sales_assist.py` | live stock in the item grid, `payment_terms_coverage()` |
| `yht_custom/report/import_gate/` | the gate as a report finance can sign |
| `yht_custom/report/stock_valuation_snapshot/` | per item/warehouse qty + rate + value |
| `yht_custom/report/customer_statement/` | ledger-based statement, replaces the mislabelled tile |
| `yht_custom/report/address_data_quality/` | the ZATCA address worklist + CSV export |
| `public/js/simple_party.js` | the quick-create dialog (list views + dashboard tile) |
| `yht_custom/doctype/branch_configuration/` | the provisioning core |
| `yht_custom/page/yht_dashboard/` | branch-user landing page |
| `public/js/branch_user_restrict.js` | navigation whitelist (usability, **not** security) |

### The five permission layers

All five are required. Skipping any one breaks the others.

1. **User Permission** rows — Company / Branch / Warehouse / Cost Center, generated by `Branch Configuration`
2. **Custom DocPerm** — which doctypes a Branch User may touch (`setup.BRANCH_USER_PERMISSIONS`)
3. **`permission_query_conditions`** — SQL list filtering (`branch_filters`)
4. **Cost-center override** at `before_validate` — replaces a cost center the user cannot see
5. **`ignore_user_permissions` Property Setters** (`setup_property_setters`) — on every field that legitimately
   references another branch's warehouse or cost center. 63 of them, derived from live metadata.

**Layer 5 removes the write-side restriction along with the form-opening block, so layer 3½ exists:**
`branch_guard.validate_branch_scope` on `validate` rejects any warehouse or cost centre outside the user's
branch. That is the real boundary — it holds on the desk, `frappe.client.save`, imports and Server Scripts.
Client-side `set_query` filters (`branch_user_forms.js`) are UX only and enforce nothing.

**Both the setters and the guard read `branch_fields.all_scoped_pairs()`.** Never hard-code that list: the first
version named two fields that do not exist in v15 and missed 27 that do, and every field in the setter list but
not the guard list is one a branch user can point at another branch with nothing checking it.

### Branch Configuration

Autonames `field:branch`, so exactly one row per Branch. Operator creates the **Branch master first**, then the
Configuration. Child tables: Warehouse, Cost Center, Mode of Payment, User+role. **First row of the Warehouse and
Cost Center tables becomes that user's default.**

On save it provisions User Permissions, upgrades Website→System users, inserts `Has Role` directly, and applies
the Module Profile. On edit it reverses cleanly — a user dropped from the table loses this branch's permissions,
and loses the role unless another Configuration still grants it.

Roles it may assign are capped to `ASSIGNABLE_ROLES` so a typo cannot grant System Manager.

### Naming series

`KS<ABBREV>-.YY.-.####`, deliberately continuing the client's existing convention — `KSIN-`, `KSDN-`, `KSPI-`,
`KSEPI-` already have this shape, so history stays readable.

**Counter isolation depends on the abbreviation.** Frappe keys `tabSeries` on the fully resolved prefix, so
`KSIN-26-` and `KSPI-26-` are separate counters. A prefix without the abbreviation makes every doctype share one
counter — the exact trap the legacy site fell into.

Returns get their own abbreviations, because a credit note is not "a sales invoice, return flavour" to an
accountant: SI→`CN`, DN→`DRN`, PI→`DBN`, PR→`PRN`.

## Rules

- **Never edit `apps/frappe` or `apps/erpnext`.** Custom Fields and Property Setters ship as fixtures; schema
  changes ship as patches in `patches/` + `patches.txt`.
- **`frappe.qb` or parameterised SQL only.** No f-string SQL. The one exception is
  `permission_query_conditions`, which must return a SQL string and has no parameter binding — there,
  `frappe.db.escape` on every value, always.
- **`cint` / `flt` / `cstr`** on anything user-supplied. Never bare `int()` / `float()`.
- **Every `@frappe.whitelist()` is a public HTTP endpoint.** Check `frappe.has_permission` or `frappe.only_for`
  inside it.
- Translate every user-visible string — `_()` in Python, `__()` in JS.
- DocType lifecycle goes in the controller; `hooks.py doc_events` is only for extending **another app's**
  doctype.
- `allow_on_submit` on any field written after submit. Never `parent.save()` to update a child row on a
  submitted parent — `frappe.db.set_value` on the child instead.

## Gotchas

1. **Child-table DocTypes still need a controller `.py`** on v15 even with `istable = 1`. Frappe imports it
   during migrate and raises `Module import failed` if missing.
2. **Controller class names use a raw `replace(" ", "")`, not title-case.** `Branch Configuration Mode of
   Payment` → `BranchConfigurationModeofPayment`, lowercase `of`, matching ERPNext's own `ModeofPayment`.
   Mismatch = `ImportError` on every save.
3. **Fixtures need BOTH** the record and its name in the `hooks.py` fixture filter list. A name missing from the
   filter is silently not exported.
4. **One `is_default` per (user, allow type).** Frappe rejects a second. `_grant()` only ever promotes to
   default, never demotes — another branch may own it.
5. **Website Users cannot hold desk roles.** `get_roles()` returns empty and the role assignment silently
   no-ops. `_ensure_system_user` upgrades first. Apply the same rule in any new role-assigning code.
6. **Custom DocPerm replaces standard DocPerm entirely.** The moment one Custom DocPerm row exists on a doctype,
   Frappe ignores that doctype's standard DocPerms. `preserve_standard_docperms()` mirrors them first, or
   Accounts Manager / Sales User silently lose access.
7. **Adding a dashboard tile is a TWO-file change** — `yht_dashboard.js` for the tile, and
   `branch_user_restrict.js` `ALLOWED_DOCTYPES` for the destination, or restricted users bounce straight back.
8. **Page JS does not reach existing browsers without a build-version bump.** The server re-reads the page's
   `.js` per request, so no `bench build` is needed — but the browser caches the whole page doc in
   `localStorage["_page:yht-dashboard"]`, and that only clears when the build version changes (the mtime of
   `sites/assets/assets.json`). After deploying page JS: `touch sites/assets/assets.json`. `clear-cache`, a
   worker restart and a hard refresh all fail to fix it.
9. **`app_include_js` / `app_include_css` need a `bench build`**, and nginx serves `/assets/` with no
   `Cache-Control` — bump the `?v=` counter on every change or the deploy is invisible.
10. **`bench get-app` exits rc=1 even on success** on this box — it ends with a `sudo supervisorctl status` that
    fails after the clone and pip install have already worked. Check `apps/` and `sites/apps.txt`, not the exit
    code.
11. **`install-app hrms` needs `--force`** when orphan HR/Payroll `Module Def` rows exist —
    `add_module_defs` does a plain insert and dies on `DuplicateEntryError`.
12. **`FrappeTestCase` rolls back after every test**, so fixtures built in `setUpClass` vanish after the first
    one. Build them in `setUp`.
13. **`tabSeries` has no DocType record.** `frappe.db.get_value("Series", ...)` fails — the query builder cannot
    resolve metadata for a bare table. Use parameterised raw SQL, as frappe's own `naming.py` does.
14. **`StockSettings.cant_change_valuation_method()` blocks a global valuation change** while any Stock Ledger
    Entry exists for an item with no valuation method of its own. Stamp the items first, change the setting
    second — never the reverse.
15. **Do NOT set `item_naming_by = "Naming Series"`.** `Item.autoname` then calls `set_name_by_naming_series`,
    which throws on an empty `naming_series` — blocking item creation for every group without one. Item codes
    are generated in `before_insert` instead (see `item_naming.py`), which frappe runs *before*
    `set_new_name()`.
16. **`frappe.make_property_setter` takes an args DICT.** The positional form belongs to
    `property_setter.make_property_setter`, a different function — passing positionals raises "got multiple
    values for argument 'validate_fields_for_doctype'".
17. **Saving a Module Profile leaves it locked** (it enqueues an apply-to-users job), so the next
    `after_migrate` dies with `DocumentLockedError`. Compare first and skip the save when nothing changed; clear
    a stale lock when a save is genuinely needed. `doc.lock()` also raises if already locked.
18. **`block_modules` does NOT affect permissions** — it is absent from `permissions.py` and only trims the desk
    sidebar. Do not reach for a Module Profile to restrict access.
19. **A role inserted moments ago is not in the user's cached permission set.** `frappe.clear_cache(user=...)`
    before `frappe.set_user(...)`, or every read comes back as a bare `PermissionError`.
20. **`permission_query_conditions` does NOT apply to a report.** A Script Report runs its own SQL, so nothing
    in `branch_filters` reaches it and an unscoped report shows a branch user every branch's data. That is the
    whole reason the report pack is Script Reports — a Query Report cannot call app code to scope itself. Every
    report resolves its branch through `report_scope`, which reads the same helpers the list views use.
21. **`Count(field).distinct()`, not `Count(field.distinct())`.** A pypika `Field` has no `.distinct()`; the
    DISTINCT belongs to the aggregate function. The wrong form raises `AttributeError: 'Field' object has no
    attribute 'distinct'` only when the report is actually run.
22. **Deleting a Custom Field does NOT drop its column or its data.** Step 1 deleted the legacy
    `custom_total_line_item_discount` field; thousands of legacy values stayed in the column, and redeclaring the
    field brought them back under our label, disagreeing with our own definition. After purging fields on any
    client, either drop the column or backfill it — `patches/backfill_line_item_discount_total.py`.
23. **A print-format edit does not deploy without bumping `modified` in its JSON.** `import_file` compares the
    timestamp and skips an unchanged record, so migrate reports success and changes nothing.
24. **`frappe.defaults.get_global_default` is NOT callable from a print format.** The template gets a restricted
    `frappe` namespace where `defaults` is a function, so it raises *'function object' has no attribute
    'get_global_default'*. Four formats carried it for a week and survived only because `doc.currency` was always
    truthy and short-circuited it — Journal Entry has no `currency` field and was the first to reach it. Use
    `yht_currency(doc)`, which is ordinary server-side Python.
25. **A NEW jinja method in `hooks.py` 500s EVERY WEBSITE PAGE until the workers reload.**
    `frappe.utils.jinja.get_jinja_hooks` resolves every registered path when it builds the environment, so one
    unresolved attribute raises for the whole env — and `/login` is a website page. Deploying `hooks.py` and the
    module together is not enough; the sequence must end with the worker signal.
26. **Frappe normalises HTML on save and inserts its own `<tbody>`.** A generated Letter Head came back exactly
    15 bytes longer than what was written (`<tbody>` + `</tbody>`), so an "has this changed" comparison was never
    equal and every migrate rewrote every letterhead. Emit the `<tbody>` yourself.
27. **`Payroll Period` autonames by PROMPT** — `name` must be set by hand or the insert raises "Please set the
    document name". And because an `after_migrate` step runs in ONE transaction, that one failure rolled back the
    GOSI components and Leave Types created earlier in the same step.
28. **`["in", [None, "", 0]]` never matches NULL.** SQL `IN (NULL, '', 0)` excludes NULLs, so a gap report on a
    freshly created column said 0 employees were missing a GOSI number when all 11 were. Use `["is", "not set"]`.
29. **`Selling Settings.customer_group` is a GROUP node on this site** (`All Customer Groups`), and
    `Customer.validate_customer_group` throws on one. Reading the setting straight through fails on every
    create — ERPNext's own quick entry has the same defect here. Resolve a leaf, preferring the most-used value
    on existing records (`Commercial`, 427 of 428 customers).
30. **`SUM(Stock Ledger Entry.actual_qty)` is the WRONG basis for reconciling a Bin.** This site has
    3,469 Stock Reconciliation rows and every one carries `actual_qty = 0`, because a reconciliation
    sets `qty_after_transaction` absolutely rather than posting a movement. Measured that way, 1,863
    of 2,820 bins looked broken; against the LATEST ledger row's `qty_after_transaction` and
    `stock_value`, **zero** disagree. Which also locates the SAR 74,409.27 gap: it is between stock
    and the GL, not inside the stock ledger.
31. **A SELECT alias is not visible to the WHERE of the same query.** `s.stock_value AS sle_value`
    then `WHERE … s.sle_value` raises *Unknown column 's.sle_value' in 'WHERE'*. It was only caught
    because the gate runner reports ERROR distinctly instead of folding it into FAIL — **an ERROR is
    never a pass.**
32. **A Dynamic Link join multiplies.** An Address linked to both a Customer and a Supplier came back
    twice, turning 578 addresses into 583 worklist rows — and a Data Import built from that would
    have processed the same ID twice. Collapse links per parent.
33. **A Chrome capture profile holds live session cookies, and there is more than one of them.**
    `Tools/Video Generator` carries both `.profile-capture/` and `.profile-dryrun/`; ignoring only the
    first staged eight `Default/Cookies` databases for commit. Glob `.profile-*/` plus explicit
    `Cookies` / `Login Data` / `Web Data` patterns.

## Deploy

Repo: **`git@github-yht:EnfonoTech/YHT-Custom.git`** (private). The box has a dedicated read-only deploy key at
`/home/v15/.ssh/yht_github_deploy`, reached through the `github-yht` host alias in `/home/v15/.ssh/config`. The
alias exists because the pre-existing `Host github.com` block points at the **yas_logistics** deploy key, and
deploy keys are repo-scoped — using `github.com` here authenticates as the wrong repo and is denied.

```bash
cd /home/v15/yht-bench/apps/yht_custom && sudo -u v15 -H git pull upstream main
cd /home/v15/yht-bench && sudo -u v15 bench --site yht-khobhar.enfonoerp.com migrate
sudo -u v15 bench --site yht-khobhar.enfonoerp.com clear-cache
touch /home/v15/yht-bench/sites/assets/assets.json
sudo supervisorctl signal QUIT yht-bench-web:yht-bench-frappe-web
```

### Running the test suite

**`yht-test` is the site to run tests against, not `yht-khobhar.enfonoerp.com`.** It lives on the same
bench, local-only (no DNS, no nginx, no SSL), scheduler paused, full app stack installed.

```bash
bench --site yht-test run-tests --app yht_custom --skip-before-tests
```

`--skip-before-tests` is **not optional on any site**: `hrms`'s `before_tests` hook is what deleted
4,847 client `Item Price` rows once already.

Seed the copy with client data using `scripts/seed-copy-site.sh` — and read its header first. The
client database is ~10 GB and the restore replays into the SAME MariaDB serving four LIVE client
sites on the other bench, so the script refuses to run outside 22:30–01:30 CEST. Measured: the suite
against an EMPTY `yht-test` gives 16 failures / 25 errors / 103 skipped, because it asserts the
client's real figures on purpose. The copy has to be a real copy.

**The worker signal is not optional and it is not just about speed.** Registering a new jinja method in
`hooks.py` 500s **every website page**, `/login` included, until the workers reload — `get_jinja_hooks` resolves
every registered path when it builds the environment, so one unresolved attribute takes the whole env down.
Pushing `hooks.py` and the module in the same commit does NOT avoid this: gunicorn is still holding the old
module. Measured: `/login` returned 500 for ~20 minutes after one such deploy (2026-08-20).

Two things that will bite:

- **The remote is `upstream`, not `origin`** — that is what `bench get-app` names it. `git pull origin main`
  fails.
- **`sudo -u v15` needs `-H`.** Without it HOME stays root's, ssh never reads `/home/v15/.ssh/config`, the
  `github-yht` alias does not resolve, and the pull fails with "Could not read from remote repository" — which
  looks like a permissions problem and is not.

Add `touch /home/v15/yht-bench/sites/assets/assets.json` after any page-JS change (gotcha 8).

## Tests

```bash
cd /home/v15/yht-bench && sudo -u v15 bench --site yht-khobhar.enfonoerp.com run-tests --app yht_custom
```

## Status

**Steps 2–6 done, 7.1 done. 241 tests on `main`, all passing; 329 with the pipeline suite** (1 skipped: the cross-company guard has nothing to
test on a single-company site). `main` @ `fc33a91`.

Step 5 and 6 remainder, closed 2026-08-20:

| Item | State |
|---|---|
| 5.5 item-wise discount + consolidated print total | done — `discount_totals.py`, all four selling formats |
| 5.9 Saudi national address, Short Code as title | done — `saudi_address.py` |
| 5.10 simple Customer / Supplier forms | done — `api/party.py` + `simple_party.js` |
| 6.5 bilingual branch letterhead | done — `letterhead.py`; company default deliberately unchanged |
| 6.6 report pack | done — Stock Sales · Collection · Branch Receivables |
| 6.8 HR configuration | done — GOSI, leave types, holiday list, payroll period |
| general Purchase Invoice + Journal Entry print formats | done |

Second round, also 2026-08-20:

| Item | State |
|---|---|
| 5.6 sales assist | **done** — `actual_qty` unhidden in all four item grids; due-date autofill verified |
| 6.6 Customer Statement | **done** — ledger-based; the dashboard tile no longer opens General Ledger |
| **7.1 import gate** | **done** — `Import Gate` + `Stock Valuation Snapshot` reports, 11 checks |
| Address worklist | **done** — `Address Data Quality` + a Data-Import-ready CSV |

**Still outstanding:** 5.7 pricing (blocked on B9), 6.1 branded tax invoice + 6.9 ZATCA onboarding
(blocked on CSR/OTP), 4.10 cancel rights (blocked on B8), Step 7.2–7.6 (needs the incumbent backup).

### The gate, as it stands

`bench --site … execute yht_custom.import_gate.run` — **FAIL, 7 blocking**:

    FAIL !  GL balances                Dr 70,254,978.90 / Cr 70,251,978.90 — KS-JV-26-0074
    FAIL !  Every voucher balances     1 voucher
    FAIL !  Accounting equation        Assets 2,895,481.37 vs 2,892,481.37
    FAIL !  Stock ties to GL           Bin 1,215,757.78 vs GL 1,141,348.51
    PASS !  Bins agree with ledger     0 of 2,820
    FAIL !  No negative stock          102 bins
    FAIL !  No negative stock value    1 bin
    FAIL    No stock at zero value     26 bins, 55 ledger rows
    PASS    One valuation method       0 items off Moving Average
    FAIL    Periods frozen             both 0001-01-01 (B15)
    FAIL !  No test accounts enabled   branchtest@ — keep for UAT, disable at go-live

`branchtest@` is deliberately still enabled: client UAT is 7.4 and has not happened. It is a
**blocking gate check** rather than a checklist line, because that line survived four handoffs.

### What the report pack measured

Administrator, five-year window: Stock Sales 4,995 rows by item / 30 by item group / 285 by customer, all
SAR 9,646,939.65 · Collection 783 Payment Entries (SAR 9,065,318.55) + 560 till receipts (SAR 336,843.83) ·
Branch Receivables 371 rows, SAR 2,178,821.29, matching the stored `outstanding_amount` exactly. As the branch
user: 4,897 / 1,243 / 365 rows, all inline, 180–767 ms.

### Two gaps this work surfaced, both for the client

**ZATCA will reject nearly every address.** Of 578 Saudi addresses: **578 have no district** and **535 no
building number** — both required for a Standard (B2B) e-invoice, both sourced from the Address. 111 have no
postal code and 50 carry a malformed one (`00`, `3463231`, `325478`). Run
`yht_custom.saudi_address.national_address_gaps`. This belongs in the Step 7 gate.

**GOSI needs a wage base decision.** There was no GOSI component of any kind. Three now exist, but `GOSI Wage`
ships as a `base` placeholder: the legal base is basic + housing, and this site has nine components with
"BASIC SALARY" in the name plus two different accommodation components, so it cannot be mapped automatically.
`yht_custom.hr_setup.hr_gaps` reports `gosi_wage_still_placeholder` until someone fixes it. Also: 11 of 11
active employees have no nationality flag, all 13 salary structures lack GOSI, 0 leave allocations, and no Eid
dates (lunar — never guessed).

Step 2 — app installs and migrates; `after_migrate` provisions the Branch User role, the four `Branch` custom
fields, 35 Branch User DocPerms, the Module Profile and the series machinery. Branch Configuration works end to
end. Branch `Kathoom Alkhobar` carries prefix `KS` with 16 series seeded.

Step 3 — site settings:

| Setting | Value |
|---|---|
| `Stock Settings.valuation_method` | `Moving Average` (all 4,053 items too, none blank) |
| `Stock Settings.enable_stock_reservation` | `1` |
| `Stock Settings.allow_negative_stock` | `0` |
| `Stock Settings.item_naming_by` | `Item Code` — **deliberately unchanged**, see gotcha 15 |
| `Accounts Settings.enable_common_party_accounting` | `1` (was already enabled) |
| freeze dates | still `0001-01-01` — **waiting on a date from finance** |

Item code generation is live but **inert until prefixes are set**: all 29 leaf item groups have an empty
`custom_item_code_prefix`, so codes stay manual. Nothing is blocked — the mechanism is per-group and only fires
when `item_code` is blank AND the group has a prefix. Run
`yht_custom.item_naming.get_prefix_coverage()` for the outstanding list.

**Not built yet** — tracked in `../docs/00-STUDY-AND-PLAN.md`:

- Step 4: warehouse/cost-center tree, `ignore_user_permissions` Property Setters (4.7), cancel-rights restriction
- Step 5: DN-compulsory flow, **Expense Purchase Invoice (§5.2)**, sales assist, item-code generation, Saudi
  national address
- Step 6: print formats, report pack, letterheads, HR config, ZATCA onboarding
- Step 7: import gate + go-live

**Deliberately NOT ported from RMAX Custom:** BNPL/Tabby/Tamara, Damage workflow, Landed Cost CBM distribution,
Inter-Company DN consolidation, No VAT Sale, Warehouse Pick List, and the **Inter-Branch Receivable/Payable
module** (no branch-to-branch movement inside a single-branch site).
