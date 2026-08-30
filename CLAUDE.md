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
34. **A Jinja print format gets NO letterhead unless it renders one itself.**
    `get_rendered_template` puts `letter_head` into the template args as a *string* for every
    template, but `add_header` — the macro that actually injects it — lives only in
    `standard.html`. A custom Jinja format that never writes `{{ letter_head }}` simply prints
    without one, silently. The KATC formats render it inside the OUTER table's `<thead>`, which is
    also what repeats it on page 2+ (verified: `quote Print 1.pdf` carries it on both pages).
35. **`get_letter_head` prefers `doc.letter_head` over the default, so pass `letterhead=`
    EXPLICITLY.** Precedence is explicit argument → `doc.letter_head` → the `is_default` record. On
    this site documents carry `letter_head = "KATHOOM ALKHOBAR"` (the incumbent image) or the
    dangling `"Kathoom without letterhead"` (1,266 of them), so a format rendering a bare
    `{{ letter_head }}` prints the OLD image on a new layout. Two defences, both needed: the buttons
    pass `letterhead=KATC Letterhead`, and each KATC format renders the letterhead only when it
    carries the `katc-lh` marker class — so `frappe.get_print` and email attachments are safe too.
36. **`display:flex` is unreliable under wkhtmltopdf.** 0.12.x runs an old WebKit. Every layout in a
    print format is a `<table>`. The client's supplied letterhead HTML was flex-based and was
    rebuilt as a table for exactly this reason.
37. **`<thead>` repeats the header; `#footer-html` repeats the page number — ⚠️ BUT NOT ON THIS BOX; read gotcha 44 first.** `prepare_header_footer`
    lifts `id="footer-html"` out of the rendered page and hands it to wkhtmltopdf as
    `--footer-html`, which is the ONLY way `<span class="page">` / `<span class="topage">` resolve —
    a browser print dialog leaves them empty, which is why the buttons use `download_pdf` rather
    than `/printview?trigger_print=1`. Hide it in the browser view with
    `.print-format-gutter #footer-html { display: none; }`. And the `<thead>` trick only works if the
    outer `<tbody>` cell sets `page-break-inside: auto` — a table cell defaults to `avoid`, which
    shoves the whole document onto one page.
38. **The Arabic item name lives on the CHILD ROW, under a per-doctype fieldname** (extends gotcha
    22 with measured counts). `Sales Invoice Item.custom_item_arabic_name` 11,507 rows,
    `item_arabic_name` 8,055; `Quotation Item.custom_item_name_in_arabic` 20,850; Delivery Note Item
    7,356; Sales Order Item 6,096. At **Item** level, `custom_item_name_in_arabic` has a column and
    3,857 rows but **no DocField** — purged, data left behind — so the old `yht_item_ar` was reading
    orphaned data and worked only by accident. Read the row first (it is already loaded: no query),
    fall back to Item once per distinct `item_code` per request, never per row.
39. **`Bank Account` must be read with `frappe.db`, never `frappe.get_doc` — including from a print
    format.** `erpnext`'s controller calls `frappe.has_permission("Bank Account", ptype="read",
    doc=…, throw=True)`, which **no `ignore_permissions` flag suppresses**, and this project denies
    branch users that read on purpose. This already broke the payment flow once. The same trap
    applies to `frappe.db.get_value` *inside a template*: the print sandbox rebinds `frappe.db.*` to
    `safe_exec`'s permission-checked wrappers, which throw for a role lacking `read`. Resolve
    anything a print format needs in ordinary server-side Python in `print_helpers`, and hand the
    template a plain dict.
40. **A `Letter Head` CANNOT be created as `source = "HTML"` in one call.**
    `LetterHead.before_insert` runs `self.source = "Image"` unconditionally ("for better UX, let
    user set from attachment") *after* the field values are applied, so the `source` handed to
    `get_doc` is discarded on every insert. It survives only because `set_image()` returns early
    when `image` is empty — so the bilingual `content` prints correctly while the desk shows an
    Image letterhead with no image, and attaching one silently replaces the whole block. Put it
    back with `db_set("source", "HTML")` after `.insert()`, and **compare `source` in the
    "has this changed" check** or the repair branch is unreachable on every later migrate. Same
    method, same hazard: `validate_disabled_and_default` sets `is_default = 1` whenever the site
    has no other default.
41. **`download_pdf`'s language parameter is `language`, not `_lang`.** Frappe's own printview
    toolbar builds `&_lang=`, which is where it gets copied from — but the API handler filters
    `frappe.form_dict` through `get_newargs`, so `_lang` never reaches
    `frappe.utils.print_format.download_pdf(doctype, name, format, doc, no_letterhead, language,
    letterhead)` and the print silently runs in the user's language. A Print Format's
    `default_print_language` does NOT cover this either: it is read only by Notification and
    Workflow Action, never on the print/PDF path.
42. **`row_net × document_vat_rate` is the wrong way to print a per-line tax.** It is right only
    when every line carries the same single `On Net Total` charge. One zero-rated line, a second
    `On Net Total` charge (the rates ADD), an `Actual` charge (`rate` is 0, so the whole column
    prints `0.00`) or an inclusive tax each give a column that does not sum to the VAT total
    printed below it. ERPNext already did the split: read `taxes[].item_wise_tax_detail`, keyed on
    `item_code or item_name`. Two shapes are in the wild — `[rate, amount]` and the current
    `{"tax_rate", "tax_amount", "net_amount"}` — and the stored amounts are in **company**
    currency (`× conversion_rate`), so scale the map — but scale it onto the CONTRIBUTING ROWS'
    own total, never onto `doc.total_taxes_and_charges`.
    🔴 **AND DECIDE MEMBERSHIP ON `Account.account_type`, NOT ON `charge_type` AND NOT ON WHETHER
    THE ROW CARRIES A DETAIL MAP.** ERPNext calls `set_item_wise_tax` for EVERY charge type unless
    the document is consolidated or carries `dont_recompute_tax`
    (`erpnext/controllers/taxes_and_totals.py:544-545`), and distributes an `Actual` charge across
    the lines as `item.net_amount * actual / doc.net_total` (`:517-518`) — so a freight row DOES
    arrive with a populated map, and "no detail" never fires. Excluding every `Actual` row is the
    opposite error: measured on YHT, `KSSQ-26-0793` is SAR 100 freight on an Expense account (must
    be excluded) while `KSIN-26-0092`'s only tax row is SAR 1.05 `Actual` on
    `200602 - VAT OUTPUT 15%`, which IS the VAT (must be kept). `account_type == "Tax"` separates
    them; read it with `frappe.db.get_value`, which runs no permission check.
43. **`Total after Discount` is not `net_total`.** `net_total` only carries the additional discount
    when `apply_discount_on == "Net Total"`; with the discount on Grand Total it is still the
    pre-discount figure, so the line prints the same number as `Total`. And print
    `rounded_total or grand_total`, never bare `grand_total` — ERPNext derives `in_words` from the
    former, so with rounding on, the figure and the words disagree on a customer-facing document.
44. 🔴 **THIS BOX'S `wkhtmltopdf` IS BUILT AGAINST AN UNPATCHED QT, SO HEADERS AND FOOTERS DO NOT
    EXIST — and neither does the `<thead>` repeat. This CORRECTS gotcha 37.** `wkhtmltopdf
    --version` prints a bare `0.12.6` with no `(with patched qt)`, and `--extended-help` says so
    outright: *"compiled against a version of QT without the wkhtmltopdf patches … some features
    are missing"*. Measured on EFTSP-013, three ways: `--footer-center "x"` produces a
    byte-identical PDF; frappe's extracted `--footer-html` (confirmed present in
    `prepare_options`, pointing at a real temp file) renders nothing; and a `<thead>` does **not**
    repeat on page 2 even for a 120-row table, with or without `page-break-inside: auto`. So on
    this bench **`Page N of M` cannot resolve and a letterhead cannot repeat on page 2 by any
    markup route** — `--header-html` is equally dead. Anything that needs either has to wait for a
    static/patched wkhtmltopdf build, or move the format to the `chrome` `pdf_generator`. Check
    the build before promising a client page numbers.
45. 🔴 **A SECOND `<span dir="ltr">` ON ONE RTL LINE OVERLAPS UNDER wkhtmltopdf.** The KATC
    letterhead's Arabic address line wrapped three numerics that way and came back as two runs of
    glyphs printed on top of each other; the CR/VAT line did the same. One span per line is fine —
    the phone and e-mail lines render correctly. A **bare digit run needs no span at all**: the
    bidi algorithm already reads European numerals left-to-right inside an RTL paragraph. This is
    invisible in the browser print view and only a rendered PDF shows it, which is exactly why the
    spec says to verify RTL by rendering rather than by reading.
46. ⚠️ **Letterhead column percentages must sum to 100.** The KATC head shipped 47% / 23% / 47%
    (= 117%) straight out of the artefact's own proportions. With `white-space: nowrap` on the
    company names the table then exceeds the page, `--disable-smart-shrinking` is on for
    wkhtmltopdf > 0.12.3, and the right-most (Arabic) column is clipped mid-word. 42/16/42 fits;
    the logo column only has to clear the image's fixed `31mm`.
47. 🔴 **A PRINT FORMAT'S CSS `pt` IS NOT A PDF `pt` — NEVER COMPUTE A PAGE POSITION BY ADDING
    THEM UP.** Measured on the KATC no-letterhead spacer: raising it from **24 pt to 154 pt**, a
    130 pt change, moved the rendered body **99.7 pt** — a factor of ≈0.767, consistent across
    formats. So "the letterhead band is 86.2 pt, therefore 86.2 + 24 = a 110 pt spacer" is wrong
    twice: 110 pt actually produced a 3.7 pt drop, not 24. Set any such length by rendering,
    measuring with `pdftotext -bbox`, and solving — the spec's own rule, and the reason
    `katc_letterhead.NO_LH_SPACER_PT` carries its measurement in a comment. It is also why the
    number lives in ONE place: seven format JSONs reach it through `yht_katc_spacer_pt()`.
48. ⚠️ **`pdf_generator: "chrome"` on a Print Format does NOTHING unless an app implements the
    `pdf_generator` HOOK. This narrows gotcha 44's escape route.** `frappe/utils/print_utils.py:44`
    really does fall back to `frappe.get_cached_value("Print Format", …, "pdf_generator")`, and the
    field really is on the DocType in v15.118.0 — but `:69-97` only routes a non-`wkhtmltopdf`
    value through `frappe.get_hooks("pdf_generator")`, and if no hook returns bytes it drops
    through to `get_pdf()`, i.e. wkhtmltopdf. No installed app on this bench (frappe, erpnext,
    hrms, ksa_compliance, arabic_translation, grey_theme, yht_custom) registers one; that hook
    ships with `print_designer`. So switching engines is an app install plus a full layout
    re-verification, not a JSON field.
49. ⚠️ **`frappe.log_error(title, message)` — the FIRST positional is the title, and it is 140
    characters.** Passing a long diagnostic first raises `CharacterLengthExceededError` *from
    inside the error logger*, which then aborts whatever was only trying to warn. Pass keywords.
    Several older call sites in this app still pass the message first; they survive only because
    their text is short.
50. ⚠️ **`FrappeTestCase` rolls back once per CLASS, not per test — this corrects gotcha 12.**
    `frappe/tests/utils.py:46` registers the rollback with `addClassCleanup(_rollback_db)`. A test
    that flips a shared column (here: taking `is_default` off every `Letter Head` to exercise the
    guard) leaks into every later method of the same class — alphabetical order decides who sees
    it. Restore what you changed in a `finally`.

51. 🔴 **AN AMPERSAND IN A SCRIPT REPORT'S NAME MAKES IT UNOPENABLE.** Frappe resolves the
    report's Python module by scrubbing its NAME, and `frappe.scrub` only replaces spaces and
    hyphens (`frappe/__init__.py:1475`) — `&` survives. "KATC Party & Account Ledger" resolved
    to `...report.katc_party_&_account_ledger`, not a legal module name, and the desk raised
    `ModuleNotFoundError` for anyone who opened it. **Every test passed**, because they imported
    the module by a slug written in the test file rather than resolving it the way the desk
    does. Test a report by scrubbing its STORED name and asserting the result matches
    `^[a-z_][a-z0-9_]*$` before importing.
52. 🔴 **THE GRID HAS AN ELEVEN-UNIT BUDGET AND FAILS BY DROPPING COLUMNS SILENTLY.**
    `grid.js:setup_visible_columns` starts `total_colsize = 1`, adds each visible column's width
    and hits `if (total_colsize > 11) return false;` — which stops the loop dead, so every
    column AFTER the overflow simply never renders, with no error. Unhiding `uom` ran the total
    to `item_code 4 + qty 2 + uom 2 + discount 2 = 11`, `rate` took it to 13, and **Rate, Amount,
    Warehouse and Stock all disappeared together**. Set `columns` explicitly on every column in
    the set and make them sum to ≤ 10.
53. 🔴 **`row.toggle_editable(field, …)` IS A SILENT NO-OP ON A FRESHLY LOADED GRID.** It routes
    to `grid_row.set_field_property`, which writes into `grid_form.fields_dict` /
    `on_grid_fields_dict` and returns early on `if (!field) return;`. A grid row builds both
    lazily, so on a form just loaded from the server they are EMPTY. Use the six-argument
    `frm.set_df_property("items", "read_only", 1, frm.doc.name, "rate", row.name)`, which
    resolves a per-row docfield through `frappe.meta.get_docfield` and refreshes that one cell.
54. 🔴 **`map_docs` PASSES THE DIALOG'S `args` POSITIONALLY INTO SLOT THREE, AND ERPNEXT'S
    MAPPERS DISAGREE ABOUT WHAT SLOT THREE IS.** `delivery_note.make_sales_invoice(source,
    target, args)` vs `sales_order.make_sales_invoice(source, target, ignore_permissions, args)`
    — so "Get Items From > Delivery Note" worked and "> Sales Order" 417'd with
    `FrappeTypeError: 'ignore_permissions' should be Union[int, bool, float]`. The desk swallows
    it: the dialog closes and the invoice is left empty. Fixed with an
    `override_whitelisted_methods` shim that dispatches on TYPE, not position.
55. ⚠️ **`get_mapped_doc` accepts a JSON STRING or a Document as `target_doc`, not a raw dict.**
    A dict reaches `target_doc.has_permission` and raises `AttributeError`. The desk sends a
    string; a test that passes a dict fails for a reason that has nothing to do with the code
    under test.
56. ⚠️ **A dismissed frappe dialog leaves its backdrop in the DOM.** Clicking the header close
    hides the modal but the backdrop stays, so the NEXT dialog's buttons exist and are covered —
    Playwright refuses the click for 30 s while the element sits right there. Hide via
    `frappe.ui.open_dialogs.forEach(d => d.hide())`, remove `.modal-backdrop`, then click
    in-page rather than through Playwright's actionability check.
57. ⚠️ **A capture clip much longer than its narration is as bad as one that is too short.**
    `fit-clips` retimes to the window, so a 50 s clip under a 15 s frame becomes a 0.29 factor —
    visible fast-forward. The head of a report clip is loading, which the narration never
    describes: trim the head, keep the tail, aim for ~1.15× the narration.

58. 🔴 **A `startswith(prefix)` GUARD ON `naming_series` MAKES THE RETURN SERIES UNREACHABLE.**
    `branch_defaults.set_naming_series_from_branch` honoured a series that already starts
    with the branch prefix, as "the operator picked it on purpose". But the form pre-fills
    the branch's own invoice series — `KSIN-.YY.-.####`, which starts with `KS` — on EVERY
    Sales Invoice, so the guard fired before the `use_for_return` branch ever ran and a
    credit note took the invoice counter. **Blanking the field does not help:**
    `Document.insert` calls `_set_defaults()` before `before_insert`, so the default comes
    straight back. Measured: a return inserted as `branchtest` came out `KSIN-26-0609`; with
    the guard fixed, `KSCN-26-0001`. The guard now never protects the branch's series for
    the OTHER return flavour. ⚠️ **And the test was green throughout** — it asserted the
    `RETURN_SUFFIX_OVERRIDES` constant and the `naming_series` options string, i.e. the
    configuration, never the hook's output. Assert what the hook DOES.
59. 🔴 **`frappe.listview_settings["X"] = { … }` IS A WHOLESALE ASSIGNMENT IN ERPNEXT, AND
    THE LIST BUNDLE LOADS AFTER `app_include_js`.** `sales_invoice_list.js` opens with that
    assignment on line 5, and a doctype's list JS is fetched when the list is first opened —
    long after boot. Anything merged into that object from `app_include_js` is discarded
    silently: no error, the button simply never appears. Attach from `frappe.router.on(
    "change")` instead.
60. 🔴 **THE LIST VIEW CLEARS ITS INNER TOOLBAR AFTER THE FIRST RENDER, SO ADD-ONCE LOSES.**
    Following gotcha 59, adding the button once behind a `__done` flag worked on an in-app
    route to the list and produced an EMPTY toolbar on a cold load — measured both ways, the
    add had run and the flag was set. Key on the button being present in
    `page.inner_toolbar` and re-check for a few seconds.
61. ⚠️ **`frappe.new_doc` RESOLVES BEFORE THE FORM EXISTS, AND HOW LONG THAT TAKES DEPENDS
    ON THE CALLER.** From a list view `cur_frm` is the new form almost at once; from a Page
    (the branch dashboard) it is not. A single `if (!cur_frm …) return;` readiness check
    therefore passed on the list and returned SILENTLY on the dashboard, leaving an ordinary
    Sales Invoice open with `is_return` clear — the operator's next click was a sale, not a
    credit note. Poll for `cur_frm.doc.__islocal` with the right doctype instead.
62. ⚠️ **A BRANCH USER CANNOT OPEN ANY NAMED WORKSPACE, SO A SHORTCUT THERE IS NOT THEIR
    ROUTE.** `branch_user_restrict.js` whitelists the literal slug `workspace`, but
    `/app/branch-user` has slug `branch-user`, so every named workspace redirects to
    `yht-dashboard` — verified live. Workspace shortcuts are for managers; a branch user
    reaches the same thing through a dashboard tile or a list-view button.
63. ⚠️ **THE SERVER CLONE HAD UNCOMMITTED EDITS FROM DIRECT `scp` DEPLOYS, AND THEY BLOCKED
    `git pull` — WHILE `set -e` DID NOT NOTICE.** Iterating by copying files onto the box
    leaves the worktree dirty, and the next pull aborts with "local changes would be
    overwritten". Piping the pull into `tail` hides the non-zero exit from `set -e`, so the
    script cheerfully went on to `migrate` and `restart` and printed DEPLOYED having deployed
    nothing. Back up, `git reset --hard FETCH_HEAD`, and check `git log --oneline -1` on the
    box as part of every deploy.

64. 🔴 **THE RETURN ABBREVIATIONS WERE INVENTED, AND TWO OF THEM COLLIDED WITH A LIVE
    COUNTER.** `RETURN_SUFFIX_OVERRIDES` shipped CN / DRN / DBN / PRN "continuing the
    client's convention". It did not: measured, the client uses `KSSR-` (98 of 102 sales
    returns), `KSDR-` (34 of 38), `KSPR-` (56 of 60) and `KSPRR-` (4 of 4), and the four
    invented series had **zero** documents between them. Worse, `SERIES_TARGETS` gave
    Purchase Receipt `PR` — which IS the purchase-invoice return prefix, 56 documents,
    counter `KSPR-26-` at 11 — and Stock Reconciliation `SR`, the sales-return prefix.
    Frappe keys `tabSeries` on the resolved prefix, so each pair was one shared counter.
    The fix is one invariant test: **no two document kinds may share an abbreviation**,
    forward or return. Write that test before adding a series, not after.
65. 🔴 **`enforce_delivery_note_route` HAD NO `is_return` BRANCH, SO A BRANCH USER'S
    CREDIT NOTE COULD NEVER RETURN STOCK.** It forced `update_stock = 0` unconditionally.
    A return is not symmetric with a sale: how the goods LEFT dictates how they come back,
    and ERPNext itself throws when a return ticks `update_stock` and its original did not
    (`sales_and_purchase_return.py:76-81`). So on a legacy direct-stock invoice the goods
    had nowhere to go — measured, `is_return=1, update_stock=1` in, `0` out. Both forward
    guards now return early on `is_return` and `return_flow` owns the return case.
66. 🔴 **NOTHING IN ERPNEXT NEGATES A TYPED QUANTITY, AND THE SIGN CHECK RUNS AT A
    DIFFERENT LIFECYCLE STAGE PER DOCTYPE.** *"For an item {0}, quantity must be negative
    number"* is thrown in exactly one place, `StatusUpdater.validate_qty`
    (`status_updater.py:248`) — at `validate()` for Sales/Purchase Invoice
    (`accounts_controller.py:262`) but only at `on_submit()` for Delivery Note and
    Purchase Receipt. The only automatic negation is the Create > Return mapper's
    `update_item`, which a user ticking the box by hand never goes through. `before_validate`
    is the one event ahead of all four. Mirror the mapper's field set exactly — `qty`,
    `stock_qty`, plus `received_qty` / `rejected_qty` / `received_stock_qty` on the buying
    side — or a return passes `validate` and fails at `on_submit`.
67. 🔴 **THE OVER-RETURN GUARD KEYS ON THE JOIN FIELD AND DEGRADES TO A MESSAGE WHEN IT IS
    BLANK.** `validate_returned_items` → `validate_quantity` keys on `(item_code, dn_detail)`
    for Delivery Note and `(item_code, sales_invoice_item)` for Sales Invoice. Measured: a
    second full return with `dn_detail` intact raises `StockOverReturnError`; with it wiped
    the same document saves with only a msgprint. **Sales Invoice has no second guard at
    all** — `on_submit` sets `self.status_updater = []` for every return unless
    `update_billed_amount_in_sales_order` is ticked (1 of 101 documents here). And there is
    **no `per_returned` field on Sales Invoice**; return percentage is tracked on Delivery
    Note and Purchase Receipt only.
68. 🔴 **`sales_invoice.make_delivery_note` CANNOT BUILD A RETURN, SO "AUTO-CREATE THE
    DELIVERY RETURN FROM THE CREDIT NOTE" IS NOT IMPLEMENTABLE.** Its row condition is
    `doc.qty - doc.delivered_qty > 0`, false for every negative line — run against a real
    return it produced a Delivery Note with **zero items**. `is_return` is `no_copy = 1` on
    both DocTypes, so even a forced mapping yields an ordinary OUTWARD note. And the
    over-return guards are scoped per `(doctype, return_against)`, so an SI return and a DN
    return covering the same goods never see each other — stock comes back twice, silently.
    The native flow runs the other way: `Delivery Note.issue_credit_note` calls
    `make_return_invoice()` on submit, which maps, sets `is_return`, saves AND submits the
    credit note — one-to-one, and it populates `delivery_note` + `dn_detail` so gotcha 67's
    guard actually fires.
69. ⚠️ **ERPNext's Delivery Note dashboard has NO "Delivery Note" entry**, so a delivery
    return never appears in the Connections of the note it reverses, even though
    `return_against` is right there on the parent. Sales Invoice does it through
    `non_standard_fieldnames["Sales Invoice"] = "return_against"`; Delivery Note simply
    omits it. Added via `override_doctype_dashboards`, whose handler is called as
    `frappe.get_attr(hook)(data=data)` — the keyword is `data`.
70. ⚠️ **A STANDARD FIELD CANNOT BE MOVED WITH `insert_after`** — that property belongs to
    Custom Field. The only lever is the DocType's `field_order` Property Setter, and a field
    takes its tab, section and column purely from WHERE IT LANDS in that list. So moving one
    silently changes its tab if the anchor is in a different one, and dropping a fieldname
    removes the field from the form entirely — assert the new order is a permutation of the
    old before writing it.

71. 🔴 **"THE ORIGINAL DID NOT CARRY ITS OWN STOCK" IS NOT "THE GOODS WENT OUT ON A NOTE".**
    It equally means the original moved NO goods — a service line, a non-stock item, an
    expense bill. A return guard that conflated the two refused returns against 345 expense
    invoices, 366 purchase invoices with no receipt and 150 sales invoices with no delivery
    note, and for an expense bill it was unsatisfiable **by construction**: `Purchase Receipt
    Item.item_code` is `reqd = 1` while `Purchase Invoice Item.item_code` is not, which is
    exactly why an expense invoice is a flagged Purchase Invoice rather than a receipt. Ask
    whether the ORIGINAL has a stock document behind it, never infer it from `update_stock`.
72. 🔴 **EXEMPTING RETURNS FROM A `update_stock` RULE OPENS A HOLE UNLESS THE RETURN'S OWN
    ROWS ARE CHECKED.** Letting a return keep `update_stock` because its original carried
    stock, without looking at the return's rows, let a branch user tick *Is Return* against
    any of 950 legacy direct-stock invoices and post ANY item at ANY quantity into the
    warehouse. ERPNext is no backstop: its over-return guard keys on `sales_invoice_item` /
    `purchase_invoice_item`, which a hand-typed row does not have, and its own `update_stock`
    check is written `if doc.doctype == "Sales Invoice"` — so the purchase side, where the
    movement is OUTBOUND, had strictly less protection. Require the row link on any
    stock-moving return; measured, 145 of 145 real rows already carry it.
73. ⚠️ **A HANDLER REGISTERED ON BOTH SIDES NEEDS BOTH SIDES' WORDING.** `STOCK_LINK` covered
    Sales and Purchase Invoice, but both `frappe.throw` messages said *"Open the Delivery
    Note, use Create > Sales Return, and tick Issue Credit Note"*. A buyer returning goods to
    a supplier has no Delivery Note, no Sales Return menu entry and no Issue Credit Note
    checkbox — an instruction they cannot follow is worse than no instruction.
74. 🔴 **`frappe.db.commit()` IN A TEST IS PERMANENT — `tearDown`'s rollback CANNOT UNDO IT.**
    `test_existing_entries_survive_a_reseed` appended a marker series to the real Purchase
    Invoice `naming_series` options and committed, so `_TEST-KEEPME-.YY.-.####` became a
    choosable entry in the live picker on every site the suite had ever run against — and the
    union in `_sync_naming_series_options` then preserved it forever by design. The commit was
    never needed: the code under test reads through `frappe.db` in the same transaction and
    sees the uncommitted write. Restore what a test changes in a `finally`, and never commit.

75. ✅ **A PRINT FORMAT CAN `{% include %}` AN APP TEMPLATE, SO A VARIANT IS A FLAG RATHER
    THAN A COPY.** `printview.get_rendered_template` compiles the format with
    `jenv.from_string(...)`, but `get_jenv` builds a `FrappeSandboxedEnvironment(loader=
    get_jloader())` — a real loader over every app's template paths — so
    `{% include "yht_custom/templates/includes/katc/quotation.html" %}` resolves, and a
    `{% set %}` before the include IS visible inside it. Verified live. Each KATC document
    now has ONE template and the Print Format records are two-line shims. The pair this
    replaced carried a comment reading *"KATC Quotation and KATC Quotation Arabic must stay
    identical outside the `katc-ar-col` cells — edit BOTH, or the check fails"*; that trap
    was about to multiply from one pair to four.
76. 🔴 **A TEST THAT ASSERTS "EXACTLY ONE DIFFERENCE" CAN HOLD A REAL DEFECT IN PLACE.**
    `test_the_arabic_quotation_differs_by_exactly_one_column` compared the Arabic format to
    the plain one with the Arabic cells stripped and demanded equality. The client artefact
    also carries a VAT / bank block that the plain format does not — so the honest fix
    *failed the test*, and adding the block to both would have put a bank block on a document
    that has none. A same-shape assertion is only safe while the shapes are genuinely meant
    to match; when the artefact says otherwise, the test changes with the format.
77. ⚠️ **ONE TEMPLATE SERVING TWO DOCTYPES MUST READ EVERY DOCTYPE-SPECIFIC FIELD WITH
    `doc.get()`.** The proforma template now backs both a Sales Order and a Quotation, and a
    Quotation has no `delivery_date`. Frappe's print env uses `DebugUndefined`, so an
    unguarded `doc.delivery_date` does not raise — it renders the literal marker text onto a
    customer-facing PDF.
78. ⚠️ **THE "NO LH" FORMATS WERE NOT LETTERHEAD VARIANTS.** For Sales Invoice and Delivery
    Note, Print 1 and Print 2 really are one document with the header toggled — proven three
    ways (byte-identical text streams, the letterhead JPEG as the only differing image,
    matching ink bands). For Quotation and Sales Order they are DIFFERENT DOCUMENTS: the
    Quotation "No LH" carries bilingual headers, bank details and a VAT number the plain one
    does not. And the Sales Order "No LH" emitted its spacer UNCONDITIONALLY, which is why
    there was no with-letterhead plain Sales Order at all until the spacer became
    `{% if letter_head %}…{% elif no_letterhead %}…{% endif %}`.

79. 🔴 **THE ARABIC OVERFLOW WAS A BIDI *ANCHORING* BUG, NOT A WIDTH PROBLEM — this
    REPLACES the old 79/80.** This wkhtmltopdf mis-computes the alignment offset of a
    right-aligned RTL line **unless the line contains no U+0020 AND its first and last
    characters are strong RTL**. Both conditions; neither alone. Measured through
    `download_pdf` across eight markup variants: `white-space: nowrap`, `<span dir="rtl">`
    and a single trailing RLM all do nothing; `word-break`/`word-wrap` are logged as
    *Unknown Property* and ignored. The overflow scaled with **word count, not width** — a
    single 28-character Arabic token (99 pt) sat perfectly inside a 193 pt column while
    four short words ran 46 pt past the rule. **Fix: join with U+00A0 and wrap every line
    in U+200F at both ends** (`print_helpers._rtl`). Three earlier attempts failed because
    they all tuned a character budget, which could never have worked.
80. ⚠️ **A REAL SHAPER PREDICTS THE WIDTH; A CHARACTER MODEL DOES NOT.** Pillow in the
    bench venv has RAQM/HarfBuzz, and `getlength(text, direction="rtl", language="ar")`
    matches the drawn width to within 0.09% over nineteen strings. The old
    1.0/1.45-per-character weighting is what failed, not modelling as such. Measure with
    `fc-match sans-serif` — on this box every family in the CSS stack resolves to
    **DejaVu Sans**, and `fc-list :lang=ar` returns only DejaVu, so the "Noto Naskh
    Arabic" in the letterhead stack is a no-op.
81. ⚠️ **`get_pdf(html)` IS NOT THE USER'S PATH AND WILL HIDE A LAYOUT BUG.** It does not
    apply the Print Format / Print Settings page geometry, so it renders on a wider page:
    `frappe.utils.pdf.read_options_from_html` regex-scrapes margins out of the format's
    own CSS, making the real items table 567.1 pt where A4-minus-defaults predicts 510.2.
    Verify layout ONLY through `frappe.utils.print_format.download_pdf(...)`, reading
    `frappe.local.response.filecontent`. Three fixes shipped broken because they were
    checked through `get_pdf`.
82. ⚠️ **DETECT OVERFLOW FROM THE COLUMN HEADER, NOT FROM RULE GEOMETRY.** `scripts/
    katc_ar_overflow.py` is the objective check. Two traps it encodes: the borders are
    NOT full-height rules (wkhtmltopdf draws `border: 1px` as a separate short segment per
    cell — 366 vertical edges on one page), so cluster the edges crossing the HEADER ROW's
    y-band; and the letterhead is Arabic too, so only check glyphs BELOW the header or the
    company name reads as an overflow. Clustering by total coverage instead picked a rule
    at 268.5 where the real one is 177.5 and reported ten good documents as broken. **The
    detector must be two-sided-verified — it FAILS the pre-fix build (17 escaping glyphs,
    worst +53.27 pt) and passes 39 of 39 after.**
83. ⚠️ **THE COLUMN HEADER DOES NOT REPEAT ON PAGE 2** (gotcha 44), so any check anchored
    on it skips every continuation page — exactly where a long document's Arabic is. Carry
    page 1's column geometry forward.
84. 🔴 **`frappe.get_print` COMMITS THE OPEN TRANSACTION.** A probe that inserted temporary
    Print Formats and relied on `frappe.db.rollback()` left them on the site. Anything that
    renders a print during a read-only investigation must build fixtures in memory and pass
    `doc=`, never `save()`.
85. ⚠️ **`is_return` IS READ-ONLY ON DELIVERY NOTE AND PURCHASE RECEIPT** (`read_only = 1`,
    versus `0` on Sales Invoice and Purchase Invoice), so a "new return" entry point cannot
    exist for those two — their returns must be raised from the document being reversed. On
    the branch dashboard they are filtered LISTS, not create tiles.

86. 🔴 **THE ARABIC *LABELS* CARRY THE SAME ANCHORING BUG AS THE VALUES — fixing one
    without the other looks fixed and is not.** After the item names were anchored, the
    column HEADINGS still drew on top of each other: `كمية` (QTY) over
    `اسم الصنف بالعربي`, `الضريبة` over `غير شامل الضريبة`, and on the Tax Invoice
    `الرقم الإضافي` over its own value. Same rule as gotcha 79 — only MULTI-WORD runs
    break, single tokens like `وصف` are fine. 39 literals across six files, 18 in the Tax
    Invoice alone. Every Arabic literal in every format is now RLM-wrapped and
    NBSP-joined, and `TestArabicLabelsAreAnchored` fails the build if a bare multi-word
    run reappears. ⚠️ The generated LETTERHEAD is deliberately NOT anchored: it is
    `text-align: center`, and the bug only affects right-aligned RTL lines.
87. 🔴 **NEVER WRITE AN INVISIBLE CHARACTER AS A LITERAL THROUGH A SHELL HEREDOC.** A test
    helper meant to strip the anchoring was written as `.replace("\u00a0", " ")` and
    arrived in the file as `.replace(" ", " ")` — two identical ordinary spaces, a silent
    no-op — because the NBSP was flattened in transit. It stripped the RLM, appeared to
    work, and left every NBSP in place. Use `\u200f` / `\u00a0` escapes in source, and
    check with `repr()` rather than by eye: the two versions look identical on screen.
88. ⚠️ **A GLYPH-OVERLAP CHECK MUST IGNORE LATIN KERNING.** Comparing adjacent character
    boxes flags ordinary kerned pairs — `T` over `e` in "Total", ~1 pt — on every format.
    Filter to pairs where at least one glyph is Arabic, or the check drowns in noise and
    the real defect hides. Two-sided-verified: 6 Arabic overlaps per document before the
    label fix, 0 across all ten formats after.

89. 🔴 **A DELIVERY NOTE / PURCHASE RECEIPT RETURN CANNOT START AS A BLANK DOCUMENT, AND
    THE LIST'S OWN "+ ADD" SILENTLY GIVES YOU THE WRONG ONE.** `is_return` is
    `read_only = 1` AND `no_copy = 1` on both stock doctypes, so nothing pre-ticks it —
    not `frappe.route_options`, not a filtered list's Add button, not `frappe.new_doc`.
    A branch user opening the returns list and pressing Add got an ordinary `KSDN-` note
    with no warning. Pointing a dashboard tile at a filtered list therefore makes the
    WRONG path the obvious one. The supported route is the mapper, which needs the source:
    `delivery_note.make_sales_return(source_name)` /
    `purchase_receipt.make_purchase_return(source_name)`, both whitelisted, driven from
    `frappe.model.open_mapped_doc`. Ask for the source document instead of opening a form.
    Contrast Sales Invoice and Purchase Invoice, where `is_return` IS editable and a blank
    return is legitimate — the two families need different entry points.
90. ⚠️ **`frappe.whitelisted` IS KEYED BY THE FUNCTION OBJECT, NOT ITS DOTTED PATH.**
    `frappe.is_whitelisted` tests `method not in whitelisted` with the function itself, so
    a membership test on the string is always False — a test written that way fails
    everything and proves nothing. Resolve with `frappe.get_attr(path)` first.
91. 🔴 **A CREDIT NOTE NEEDS TWO FIELDS TO SETTLE AN INVOICE, AND `return_against` IS THE
    LESSER ONE.** `update_outstanding_for_self` ships with **default `"1"`**, and
    `accounts_controller.py:213` makes a return that has it set keep its OWN outstanding —
    so a perfectly linked credit note still leaves the original **Unpaid**. Verified:
    linked to KSIN-26-0596, still `Unpaid` at 6.00. Flip the DEFAULT with a Property
    Setter, never force the value in a hook: ERPNext's over-credit valve at
    `accounts_controller.py:222` re-sets the flag to 1 when the credit exceeds the
    original's outstanding, and forcing it would defeat that. Reproduced: a 7.00 credit
    against a 6.00 outstanding flipped itself back, correctly.
92. ⚠️ **`Delivery Note.issue_credit_note` PRODUCES AN UNLINKED CREDIT NOTE.** It maps from
    the delivery RETURN via `make_sales_invoice(<dn_return>)`, and `return_against` is a
    Sales Invoice link, so there is nothing to put in it. 9 submitted credit notes on
    `yht-test` had this gap. Walking back: credit row -> stock RETURN row -> ORIGINAL stock
    row -> the invoice row that billed it. **The sides are NOT symmetric** — `Delivery Note
    Item` has `dn_detail` and no `delivery_note_item`; `Purchase Receipt Item` has
    `purchase_receipt_item` and no `pr_detail`. And a credit note ALREADY raised against the
    same original row carries the same stock-row link, so filter `is_return` out BEFORE
    counting candidates or the ambiguity makes the lookup bail (row 177m1l8c9h matches both
    KSIN-24-6950 and the credit note KSSR-24-1027).
93. ⚠️ **THE RETURN SERIES ONLY APPLIES TO BRANCH USERS — STILL OPEN.**
    `_branch_series_rows()` returns `("", [])` for a bypass role or a user with no Branch
    Configuration, so an Administrator/manager/`uat@` return numbers into the FORWARD
    series. `KSIN-26-0609` was created that way on 2026-08-29, after the series work.
    `test_no_two_document_kinds_share_an_abbreviation` misses it because it checks the
    CONFIG, not the runtime path. Needs a client decision — a non-branch user has no branch
    prefix, so "which series" has no single right answer.
94. 🔴 **`WHERE name > 'KSDN-26-0535'` IS A STRING COMPARE, NOT "CREATED AFTER".** Used to
    clean up two test documents on 2026-08-30, it matched **every delivery return on the
    site** — `'KSDR-…' > 'KSDN-…'` because `R` sorts after `N` — then cancelled, deleted and
    committed 18 `KSDR-*` and 3 `KSRDN-*`. Naming series share a prefix stem, so a range over
    `name` silently spans sibling series (`KSSR`/`KSIN`, `KSPRR`/`KSPRN` too). Delete by an
    explicit `name IN %s` list captured as the script creates them, and print the match set
    before deleting. Better: don't commit at all — `frappe.db.rollback()` had been doing this
    job correctly all session. Recoverable from `Deleted Document`, but cancelling before
    deleting stores `docstatus: 2`, so a restore returns them **cancelled, not submitted**.
95. ⚠️ **`app_include_js` CACHE-BUSTS BY A MANUAL `?v=` STRING — BUMP IT.** Changing
    `public/js/branch_user_restrict.js` without bumping `?v=7` leaves every browser that
    already holds that URL on the OLD file, forever. The new `yht-multi-return` route was
    absent from their cached ALLOWED_ROUTES, so branch users were bounced to the dashboard.
    A headless check caught it by landing on `/app/yht-dashboard`; server-side everything
    looked correct, and `clear-cache` / `bench build` / `touch assets.json` all fail to fix
    it. `sites/assets/yht_custom` is a SYMLINK to `public/`, so there is no build step to
    blame — the stale copy is in the browser.
96. ⚠️ **`frappe.format(v, {fieldtype: "Currency"})` RETURNS BLOCK-LEVEL MARKUP.** Dropped
    into an inline header it breaks the line regardless of `white-space: nowrap`, which is
    why a one-line meta rendered as three. `getComputedStyle` reported `nowrap` the whole
    time — the wrap came from the injected element, not the CSS, so three CSS fixes in a row
    changed nothing. Use `format_currency(value, currency)` for a plain string.

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

**Tests run on `yht-test`, and ONLY on `yht-test`.** `allow_tests` is now `false` on
`yht-khobhar.enfonoerp.com` — a run there is refused by the framework, not by convention.

```bash
bench --site yht-test run-tests --app yht_custom --skip-before-tests
```

`--skip-before-tests` stays mandatory anyway: `hrms`'s `before_tests` hook is what deleted 4,847
client `Item Price` rows once already.

| | |
|---|---|
| Site | `yht-test` on the SAME bench, `/home/v15/yht-bench` |
| URL | https://yht-test.enfonoerp.com (Caddy block on control → this box:80) |
| Data | a **copy of the client database** — treat it as client data |
| Suite | **248 tests, OK** — identical to the client site |
| Manager | registered as `yht-test`, environment `staging` |

**It is neutered, and each guard matters.** `mute_emails=1` (the framework-level kill), scheduler
paused, all Email Accounts `enable_outgoing=0`/`enable_incoming=0`, all 6 Notifications disabled.
A restored copy carries the client's mail config, their notifications and their digests; a test
site quietly emailing real customers is the classic copy-site accident.

Reseed with `scripts/seed-copy-site.sh`. Read its header: the restore replays ~10 GB into the SAME
MariaDB that serves four LIVE client sites on the other bench, so it refuses outside
22:30–01:30 CEST unless `FORCE=1`. **That refusal is not theoretical** — forcing it at 20:00
pushed `elco`, `yas-logistics` and `designer-stom` to 5–10 s responses and intermittent
timeouts within three minutes. Aborted, and they recovered immediately.

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
| **client prints & HTML letterhead** | **in review, NOT done** — `KATC Letterhead` (HTML) + seven `KATC *` Jinja formats + the incumbent's toolbar buttons on all four selling doctypes. Sits BESIDE the `YHT *` set: `DEFAULT_PRINT_FORMATS` unchanged, nothing deleted, nothing re-defaulted. Held at *in review* until the wkhtmltopdf fidelity pass against `.pipeline/client-artefacts/*.pdf` is signed off — the row moves to **done** at DELIVER, not before |

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
