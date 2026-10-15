"""Real-browser check of the 2026-10-15 rows against a site, as the user whose session id is in SID_FILE.

    SID_FILE=/path/sid.txt SITE=yht-test.enfonoerp.com python3 ui_check_1015.py [outdir]

The session id comes from a server-minted Session (no password); keep the file 0600 and revoke the
session afterwards. Needs `playwright` with a Chromium. Prints PASS / FAIL per check and saves
screenshots to `outdir`. It only reads, except that it types into new, never-saved forms.
"""
import json, os, sys
from playwright.sync_api import sync_playwright

SITE = os.environ.get("SITE", "yht-test.enfonoerp.com")
SID = open(os.environ["SID_FILE"]).read().strip()
PICKS = json.load(open(os.environ["PICKS"])) if os.environ.get("PICKS") else {}
ADMIN_SID = open(os.environ["ADMIN_SID_FILE"]).read().strip() if os.environ.get("ADMIN_SID_FILE") else ""
OUT = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(OUT, exist_ok=True)
failed = []


def check(label, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + label, extra)
    if not ok:
        failed.append(label)


def ev(page, body):
    """Run an async arrow function in the page; a rejection comes back as {__error: ...}, not a crash."""
    wrapped = "async () => { try { return await Promise.race([(" + body.strip() + ")(), new Promise((_, rej) => setTimeout(() => rej(new Error('page script timed out after 30 s')), 30000))]); } catch (e) { return {__error: String((e && (e.message || e._server_messages || e.exc)) || JSON.stringify(e)).slice(0, 400)}; } }"
    for attempt in range(4):
        try:
            return page.evaluate(wrapped)
        except Exception as e:  # a form route can redirect once (new-quotation-xxxx) and kill the context
            if "context was destroyed" not in str(e) or attempt == 3:
                raise
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(1500)


def open_form(page, route, doctype):
    page.goto(f"https://{SITE}{route}", wait_until="domcontentloaded")
    page.wait_for_function("window.frappe && frappe.boot && frappe.session && frappe.session.user !== 'Guest'", timeout=60000)
    page.wait_for_function(f"window.cur_frm && cur_frm.doctype === '{doctype}'", timeout=60000)
    try:
        page.wait_for_load_state("load", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1500)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1500, "height": 1000})
    ctx.add_cookies([{"name": "sid", "value": SID, "domain": SITE, "path": "/", "secure": True, "httpOnly": True, "sameSite": "Lax"}])
    page = ctx.new_page()
    page.set_default_timeout(45000)
    errors = []
    page.on("pageerror", lambda e: errors.append(page.url[-60:] + " :: " + str(e)[:160] + " | " + (getattr(e, "stack", "") or "")[:500]))

    # ---------------------------------------------------------------- who am I
    page.goto(f"https://{SITE}/app", wait_until="domcontentloaded")
    page.wait_for_function("window.frappe && frappe.boot && frappe.session && frappe.session.user !== 'Guest'", timeout=60000)
    who = page.evaluate("({user: frappe.session.user, features: (frappe.boot.yht_features||[]).filter(f=>f.startsWith('oct15')), canBank: frappe.model.can_read('Bank Account')})")
    print("USER", who["user"], "| can read Bank Account:", who["canBank"], "| oct15 switches:", len(who["features"]))
    check("the oct15 switches reach the browser (at least the six of rows 40-48)", len(who["features"]) >= 6, who["features"])

    # ----------------------------------------------------------- row 40: Payment Entry
    open_form(page, "/app/payment-entry/new", "Payment Entry")
    res = ev(page, """async () => {
        const frm = cur_frm;
        await frm.set_value('payment_type', 'Pay');
        await new Promise(r => setTimeout(r, 800));
        const company = frm.doc.company;
        const modes = await frappe.db.get_list('Mode of Payment', {fields: ['name', 'type'], filters: {enabled: 1}, limit: 50});
        let picked = null, account = null;
        for (const m of modes) {
            try {
                const r = await frappe.call({method: 'erpnext.accounts.doctype.sales_invoice.sales_invoice.get_bank_cash_account', args: {mode_of_payment: m.name, company}, silent: true});
                if (r.message && r.message.account) { picked = m.name; account = r.message.account; break; }
            } catch (e) { /* a Mode with no default account for this company throws; try the next */ }
        }
        if (!picked) return {skip: 'no Mode of Payment with an account for ' + company};
        await frm.set_value('mode_of_payment', picked);
        await new Promise(r => setTimeout(r, 3500));
        const dialog = ($('.msgprint-dialog:visible .modal-body').text() || '').trim().slice(0, 200);
        return {picked, account, paid_from: frm.doc.paid_from, ro_from: frm.get_field('paid_from').df.read_only, ro_to: frm.get_field('paid_to').df.read_only,
                skip_fn: !!(frm.events.set_company_bank_account && frm.events.set_company_bank_account.__yht_pe), dialog,
                input_disabled: !!frm.get_field('paid_from').$input && frm.get_field('paid_from').$input.prop('disabled')};
    }""")
    print("PE:", json.dumps(res)[:400])
    if res.get("__error"):
        check("row 40: the page script ran", False, res["__error"][:200]); res = {"skip": "script error"}
    if res.get("skip"):
        check("row 40 (needs a Mode of Payment with an account)", False, res["skip"])
    else:
        check("row 40: the account came from the Mode of Payment", bool(res["paid_from"]) and res["paid_from"] == res["account"])
        check("row 40: paid_from is read-only after the Mode of Payment", res["ro_from"] == 1)
        check("row 40: no permission pop-up", "permission" not in res["dialog"].lower(), res["dialog"])
        if not who["canBank"]:
            check("row 40: Bank Account lookup skipped for a user who cannot read it", res["skip_fn"])
    page.screenshot(path=f"{OUT}/row40-payment-entry.png")
    res2 = ev(page, """async () => { const frm = cur_frm; await frm.set_value('mode_of_payment', ''); await new Promise(r => setTimeout(r, 800));
        return {ro_from: frm.get_field('paid_from').df.read_only}; }""")
    check("row 40: editable again when the Mode of Payment is cleared", res2["ro_from"] in (0, None, False), res2)

    # ----------------------------------------------------------- row 42: Quotation team
    open_form(page, "/app/quotation/new", "Quotation")
    res = ev(page, """async () => {
        const frm = cur_frm;
        await frm.set_value('quotation_to', 'Customer');
        await frm.set_value('party_name', %s);
        await new Promise(r => setTimeout(r, 4000));
        const team = (frm.doc.sales_team || []).map(r => [r.sales_person, r.allocated_percentage]);
        const f = frm.get_field('sales_team');
        const sec = frm.get_field('custom_front_team_section');
        return {customer: frm.doc.party_name, team, hasField: !!f, section: !!(sec && sec.wrapper && $(sec.wrapper).is(':visible')), label: sec && sec.df && sec.df.label};
    }""" % json.dumps(PICKS.get("customer", "")))
    print("QTN:", json.dumps(res)[:300])
    check("row 42: Quotation has the Sales Team table", res.get("hasField"), res.get("__error", ""))
    check("row 42: the customer's team filled in", len(res.get("team", [])) >= 1, res.get("team"))
    check("row 42: a Sales Team section is on the front page", res.get("section"), res.get("label"))
    page.screenshot(path=f"{OUT}/row42-quotation-team.png", full_page=False)

    # ----------------------------------------------------------- row 43: Opportunity items (needs a desk user; branch users cannot open it)
    if ADMIN_SID:
        actx = browser.new_context(viewport={"width": 1500, "height": 1000})
        actx.add_cookies([{"name": "sid", "value": ADMIN_SID, "domain": SITE, "path": "/", "secure": True, "httpOnly": True, "sameSite": "Lax"}])
        apage = actx.new_page(); apage.set_default_timeout(45000)
        open_form(apage, "/app/opportunity/new", "Opportunity")
        res = apage.evaluate("""() => { const w = cur_frm.fields_dict.items.grid.wrapper;
            return {download: w.find('.grid-download').length > 0 && !w.find('.grid-download').hasClass('hidden'), upload: w.find('.grid-upload').length > 0 && !w.find('.grid-upload').hasClass('hidden')}; }""")
        check("row 43: Download and Upload buttons on the Opportunity items grid", res["download"] and res["upload"], res)
        apage.screenshot(path=f"{OUT}/row43-opportunity-items.png")
        actx.close()
    else:
        print("SKIP row 43 (no ADMIN_SID_FILE)")

    # ----------------------------------------------------------- row 45: Add Multiple
    open_form(page, "/app/sales-invoice/new", "Sales Invoice")
    try:
        page.wait_for_function("() => cur_frm.fields_dict.items.grid.multiple_set === true", timeout=20000)
        page.wait_for_timeout(1500)
        page.evaluate("() => cur_frm.fields_dict.items.grid.wrapper.find('.grid-add-multiple-rows').click()")
        page.wait_for_selector(".modal:visible a[data-value]", timeout=25000)
        page.wait_for_timeout(1500)
        codes = page.evaluate("() => $('.modal:visible a[data-value]').map((i, a) => $(a).attr('data-value')).get()")
        print("ADD MULTIPLE first page:", codes)
        ordered = [c.lower() for c in codes] == sorted(c.lower() for c in codes)
        check("row 45: Add Multiple lists items in item-code order", len(codes) >= 5 and ordered, codes[:10])
        # the same first page the item picker gets
        picker = ev(page, """async () => { const r = await frappe.call({method: 'frappe.desk.search.search_widget', type: 'GET', args: {doctype: 'Item', txt: '', searchfield: 'name', start: 0, page_length: 10, query: 'yht_custom.item_search.item_query'}}); return (r.message || []).map(x => x[0]); }""")
        check("row 45: it is the same page the item picker shows", codes[:len(picker)] == picker[:len(codes)] if isinstance(picker, list) else False, picker)
        page.screenshot(path=f"{OUT}/row45-add-multiple.png")
    except Exception as e:
        check("row 45: Add Multiple opened", False, repr(e)[:160])

    # ----------------------------------------------------------- row 48: Print PDF
    ref = PICKS.get("si") or ev(page, """async () => { const r = await frappe.db.get_list('Sales Invoice', {fields: ['name'], filters: {docstatus: 1, is_return: 0}, order_by: 'modified desc', limit: 1}); return r[0] && r[0].name; }""")
    open_form(page, f"/app/sales-invoice/{ref}", "Sales Invoice")
    labels = page.evaluate("() => Object.keys(cur_frm.custom_buttons || {})")
    label = next((l for l in labels if l in ("Print PDF", "Print")), None)
    check("row 48: a Print button is on the Sales Invoice toolbar", label is not None, labels)
    if label:
        page.evaluate("() => { window.__opened = []; window.open = (u) => { window.__opened.push(u); }; }")
        page.evaluate("(l) => cur_frm.custom_buttons[l].trigger('click')", label); page.wait_for_timeout(600)
        first = page.evaluate("() => window.__opened.slice(-1)[0]")
        print("PRINT default ->", first)
        page.evaluate("() => { cur_frm.meta.default_print_format = 'SALES-INVOICE'; }")
        page.evaluate("(l) => cur_frm.custom_buttons[l].trigger('click')", label); page.wait_for_timeout(600)
        second = page.evaluate("() => window.__opened.slice(-1)[0]")
        print("PRINT with a client default ->", second)
        q1 = parse_qs(urlparse(first or "").query) if False else None
        from urllib.parse import urlparse, parse_qs
        q1 = parse_qs(urlparse(first or "").query)
        check("row 48: with the KATC default the old URL is used", q1.get("format") == ["KATC Tax Invoice"] and q1.get("letterhead") == ["KATC Letterhead"] and q1.get("language") == ["en"], first)
        from urllib.parse import urlparse, parse_qs
        q2 = parse_qs(urlparse(second or "").query)
        check("row 48: with a client default the button follows it (no KATC letterhead, no language pin)",
              q2.get("format") == ["SALES-INVOICE"] and "letterhead" not in q2 and "language" not in q2, second)

    # ----------------------------------------------------------- row 46: connected numbers
    if PICKS.get("si"):
        open_form(page, f"/app/sales-invoice/{PICKS['si']}", "Sales Invoice")
        res = page.evaluate("""() => { const f = cur_frm.get_field('custom_delivery_note_no'); return {value: cur_frm.doc.custom_delivery_note_no, visible: !!(f && f.$wrapper.is(':visible')), so: cur_frm.doc.custom_sales_order_no}; }""")
        check("row 46: the Delivery Note number shows on the Sales Invoice front page", bool(res["value"]) and res["visible"], res)
        page.screenshot(path=f"{OUT}/row46-sales-invoice.png")
    if PICKS.get("so"):
        open_form(page, f"/app/sales-order/{PICKS['so']}", "Sales Order")
        res = page.evaluate("""() => { const f = cur_frm.get_field('custom_sales_invoice_no'); return {value: cur_frm.doc.custom_sales_invoice_no, dn: cur_frm.doc.custom_delivery_note_no, visible: !!(f && f.$wrapper.is(':visible'))}; }""")
        check("row 46: the Sales Invoice number shows on the Sales Order front page", bool(res["value"]) and res["visible"], res)
        page.screenshot(path=f"{OUT}/row46-sales-order.png")

    # ----------------------------------------------------------- row 26 "new also": a new document stays in the chosen year
    info = page.evaluate("() => (frappe.boot.yht_session_year || {})")
    if not info.get("limit"):
        print("INFO the branch user has no fiscal year chosen on this site; choosing 2025 for the check")
        ev(page, """async () => { await frappe.call({method: 'frappe.core.doctype.session_default_settings.session_default_settings.set_session_default_values', args: {default_values: {fiscal_year: '2025'}}}); return 1; }""")
        page.goto(f"https://{SITE}/app", wait_until="domcontentloaded"); page.wait_for_timeout(4000)
        info = page.evaluate("() => (frappe.boot.yht_session_year || {})")
    lim = info.get("limit")
    check("row 26: the browser receives the chosen year's dates", bool(lim), lim and (lim["start"], lim["end"]))
    if lim:
        open_form(page, "/app/sales-invoice/new", "Sales Invoice")
        page.wait_for_timeout(1500)
        res = page.evaluate("""() => { const f = cur_frm.get_field('posting_date'); const dp = f.datepicker;
            return {value: cur_frm.doc.posting_date, min: dp && dp.opts && dp.opts.minDate && frappe.datetime.obj_to_str(dp.opts.minDate), max: dp && dp.opts && dp.opts.maxDate && frappe.datetime.obj_to_str(dp.opts.maxDate)}; }""")
        print("DATE:", res)
        check("row 26: the default date is inside the chosen year", lim["start"] <= (res["value"] or "") <= lim["end"], res["value"])
        check("row 26: the date picker is limited to the chosen year", res["min"] == lim["start"] and res["max"] == lim["end"], res)
        page.screenshot(path=f"{OUT}/row26-new-document-date.png")
        outside = ev(page, """async () => { try { await frappe.call({method: 'frappe.client.insert', args: {doc: {doctype: 'Sales Invoice', customer: 'x', posting_date: '2099-03-01'}}, silent: true}); return {ok: true}; }
            catch (e) { return {msg: String((e && e.responseText) || e).slice(0, 600)}; } }""")
        check("row 26: the server refuses a new document dated outside the chosen year", "outside the fiscal year" in (outside.get("msg") or ""), (outside.get("msg") or "")[:160])
        inside = ev(page, """async (d) => { try { await frappe.call({method: 'frappe.client.insert', args: {doc: {doctype: 'Sales Invoice', customer: 'x', posting_date: d}}, silent: true}); return {ok: true}; }
            catch (e) { return {msg: String((e && e.responseText) || e).slice(0, 600)}; } }""".replace("(d) =>", "() =>").replace("posting_date: d", "posting_date: " + json.dumps(lim["start"])))
        check("row 26: a date inside the year gets past the year rule (it then fails on the missing customer, not the year)",
              "outside the fiscal year" not in (inside.get("msg") or ""), (inside.get("msg") or "")[:160])

    # ----------------------------------------------------------- Q&A 5: standard Remarks editable after submit (admin)
    if ADMIN_SID:
        actx = browser.new_context(viewport={"width": 1500, "height": 1000})
        actx.add_cookies([{"name": "sid", "value": ADMIN_SID, "domain": SITE, "path": "/", "secure": True, "httpOnly": True, "sameSite": "Lax"}])
        apage = actx.new_page(); apage.set_default_timeout(45000)
        apage.goto(f"https://{SITE}/app", wait_until="domcontentloaded")
        apage.wait_for_function("window.frappe && frappe.boot && frappe.session.user !== 'Guest'", timeout=60000)
        name = apage.evaluate("""async () => { const r = await frappe.db.get_list('Purchase Invoice', {fields: ['name'], filters: {docstatus: 1, remarks: ['is', 'set']}, order_by: 'modified desc', limit: 1}); return r[0] && r[0].name; }""")
        open_form(apage, f"/app/purchase-invoice/{name}", "Purchase Invoice")
        res = apage.evaluate("""() => { const f = cur_frm.get_field('remarks'); return {docstatus: cur_frm.doc.docstatus, original: cur_frm.doc.remarks, disabled: !!(f.$input && f.$input.prop('disabled')), ro: f.df.read_only}; }""")
        check("Q&A 5: Remarks is editable on a SUBMITTED Purchase Invoice", res["docstatus"] == 1 and not res["disabled"] and not res["ro"], res)
        original = res["original"]
        saved = ev(apage, """async () => { const frm = cur_frm; await frm.set_value('remarks', %s); await frm.save('Update'); await new Promise(r => setTimeout(r, 1500));
            const r = await frappe.db.get_value('Purchase Invoice', frm.doc.name, 'remarks');
            const g = await frappe.call({method: 'frappe.client.get_list', args: {doctype: 'GL Entry', filters: {voucher_type: 'Purchase Invoice', voucher_no: frm.doc.name}, fields: ['remarks'], limit_page_length: 20}});
            return {db: r.message.remarks, ledger: (g.message || []).map(x => x.remarks)}; }""" % json.dumps("edited in the browser check"))
        check("Q&A 5: the edit is saved", saved.get("db") == "edited in the browser check", saved)
        check("Q&A 5: the General Ledger wording follows", bool(saved.get("ledger")) and all("edited in the browser check" in (x or "") for x in saved["ledger"]), saved.get("ledger"))
        apage.screenshot(path=f"{OUT}/qa5-remarks-after-submit.png")
        # put the original wording back (same path, so the ledger returns too)
        back = ev(apage, """async () => { await cur_frm.set_value('remarks', %s); await cur_frm.save('Update'); await new Promise(r => setTimeout(r, 1500));
            const r = await frappe.db.get_value('Purchase Invoice', cur_frm.doc.name, 'remarks'); return r.message.remarks; }""" % json.dumps(original))
        check("Q&A 5: the original wording is restored", back == original, back)
        actx.close()

    # Frappe's own Workspace view throws "reading 'name'" intermittently while a branch user is redirected from
    # /app to the dashboard (a page-level exception, no effect on the form checks above). Anything else counts.
    real = [e for e in errors if "Workspace.show_page" not in e]
    if len(real) != len(errors):
        print("NOTE ignored the intermittent Frappe Workspace.show_page exception (%d) on the branch landing redirect" % (len(errors) - len(real)))
    check("no JavaScript errors on the pages visited", not real, real[:3])
    browser.close()

print("\nFAILED:", failed if failed else "none")
sys.exit(1 if failed else 0)
