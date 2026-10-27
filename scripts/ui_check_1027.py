"""Real-browser check of the 2026-10-26 sheet rows (four fields off the forms), as the user whose session id is in SID_FILE.

    SID_FILE=/path/sid.txt SITE=yht-test.enfonoerp.com python3 ui_check_1027.py [outdir]

Same contract as `ui_check_1015.py`: a server-minted session (no password), the file 0600, the session revoked
afterwards. It only reads, except that it types into new, never-saved forms. `depends_on` and `hidden` are applied by the
desk, not the server, so this is the only check that sees what the user sees.
"""
import os, sys
from playwright.sync_api import sync_playwright

SITE = os.environ.get("SITE", "yht-test.enfonoerp.com")
SID = open(os.environ["SID_FILE"]).read().strip()
OUT = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(OUT, exist_ok=True)
failed = []


def check(label, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + label, extra)
    if not ok:
        failed.append(label)


def open_new(page, doctype):
    slug = doctype.lower().replace(" ", "-")
    page.goto(f"https://{SITE}/app/{slug}/new", wait_until="domcontentloaded")
    page.wait_for_function("window.frappe && frappe.session && frappe.session.user !== 'Guest'", timeout=60000)
    page.wait_for_function(f"window.cur_frm && cur_frm.doctype === '{doctype}'", timeout=60000)
    # `/new` re-routes to `/new-<slug>-<hash>` once the draft is named; a script run before that dies with the old context.
    page.wait_for_function(f"location.pathname.includes('/new-{slug}-')", timeout=30000)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function(f"window.cur_frm && cur_frm.doctype === '{doctype}'", timeout=60000)
    page.wait_for_timeout(2500)


def shown(page, fieldname):
    """'Write' / 'Read' when the desk draws the control, 'None' when it hides it, None when the form has no such field."""
    return page.evaluate(f"(() => {{ const f = cur_frm.fields_dict['{fieldname}']; if (!f) return null; f.refresh && f.refresh(); return f.disp_status; }})()")


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1500, "height": 1000})
    ctx.add_cookies([{"name": "sid", "value": SID, "domain": SITE, "path": "/", "secure": True, "httpOnly": True, "sameSite": "Lax"}])
    page = ctx.new_page()
    page.set_default_timeout(45000)

    page.goto(f"https://{SITE}/app", wait_until="domcontentloaded")
    page.wait_for_function("window.frappe && frappe.session && frappe.session.user !== 'Guest'", timeout=60000)
    print("USER", page.evaluate("frappe.session.user"))

    # Sales Invoice: three of the four rows live here.
    open_new(page, "Sales Invoice")
    check("SI: Other Remarks not drawn", shown(page, "custom_other_remarks") in ("None", None), shown(page, "custom_other_remarks"))
    check("SI: company Tax ID not drawn", shown(page, "company_tax_id") == "None", shown(page, "company_tax_id"))
    check("SI: customer Tax ID still a field on the form", page.evaluate("!!cur_frm.fields_dict.tax_id"))
    check("SI: Attention not drawn", shown(page, "custom_attention_person") in ("None", None), shown(page, "custom_attention_person"))
    page.evaluate("cur_frm.set_value('custom_payment_mode', 'Credit')")
    page.wait_for_timeout(800)
    credit = shown(page, "due_date")
    check("SI: Payment Due Date drawn on Credit", credit in ("Write", "Read"), credit)
    page.evaluate("cur_frm.set_value('custom_payment_mode', 'Cash')")
    page.wait_for_timeout(800)
    cash = shown(page, "due_date")
    check("SI: Payment Due Date gone on Cash", cash == "None", cash)
    page.screenshot(path=os.path.join(OUT, "si-cash.png"), full_page=False)
    page.evaluate("cur_frm.set_value('custom_payment_mode', 'Credit')")
    page.wait_for_timeout(800)
    check("SI: Payment Due Date back on Credit", shown(page, "due_date") in ("Write", "Read"))

    for dt in ("Quotation", "Sales Order", "Delivery Note"):
        open_new(page, dt)
        check(f"{dt}: Attention not drawn", shown(page, "custom_attention_person") in ("None", None), shown(page, "custom_attention_person"))
        check(f"{dt}: Other Remarks not drawn", shown(page, "custom_other_remarks") in ("None", None), shown(page, "custom_other_remarks"))
        page.screenshot(path=os.path.join(OUT, dt.lower().replace(" ", "-") + ".png"), full_page=False)

    browser.close()

print("RESULT", "FAIL" if failed else "PASS", len(failed))
sys.exit(1 if failed else 0)
