"""Real-browser check of Inter Branch Sale as a branch user (client decision of 2026-10-28: normal sales accounts, no VAT).

    SID_FILE=/path/sid.txt SITE=yht-test.enfonoerp.com ITEM=<item> python3 ui_check_inter_branch_sale.py [outdir]

yht-test ONLY: it SUBMITS one sale (a real Stock Entry and Journal Entry on the test copy). The session is minted
server-side, kept in a 0600 file, and revoked afterwards. Prints the sale's name as `SALE <name>` so the GL can be
checked server-side.
"""
import os, sys
from playwright.sync_api import sync_playwright

SITE = os.environ.get("SITE", "yht-test.enfonoerp.com")
assert SITE.startswith("yht-test"), "this check submits documents: yht-test only"
SID = open(os.environ["SID_FILE"]).read().strip()
ITEM = os.environ["ITEM"]
CUSTOMER = os.environ.get("CUSTOMER", "CU0022")
OUT = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(OUT, exist_ok=True)
failed = []


def check(label, ok, extra=""):
	print(("PASS " if ok else "FAIL ") + label, extra)
	if not ok:
		failed.append(label)


def ready(page):
	page.wait_for_function("window.frappe && frappe.session && frappe.session.user !== 'Guest'", timeout=60000)


with sync_playwright() as p:
	browser = p.chromium.launch(headless=True)
	ctx = browser.new_context(viewport={"width": 1500, "height": 1000})
	ctx.add_cookies([{"name": "sid", "value": SID, "domain": SITE, "path": "/", "secure": True, "httpOnly": True, "sameSite": "Lax"}])
	page = ctx.new_page()
	page.set_default_timeout(45000)

	page.goto(f"https://{SITE}/app/yht-dashboard", wait_until="domcontentloaded")
	ready(page)
	print("USER", page.evaluate("frappe.session.user"))
	try:
		page.wait_for_function("[...document.querySelectorAll('.yht-dashboard *')].some(e => e.children.length === 0 && /^Inter Branch Sale$/.test((e.textContent||'').trim()))", timeout=60000)
		tile = True
	except Exception:
		tile = False
	check("dashboard shows an Inter Branch Sale entry", tile)
	page.screenshot(path=os.path.join(OUT, "dashboard.png"))

	page.goto(f"https://{SITE}/app/inter-branch-sale/new", wait_until="domcontentloaded")
	ready(page)
	page.wait_for_function("window.cur_frm && cur_frm.doctype === 'Inter Branch Sale'", timeout=60000)
	page.wait_for_timeout(2500)
	check("branch user stays on the new form (not bounced)", "/app/inter-branch-sale/new" in page.evaluate("location.pathname"), page.evaluate("location.pathname"))
	page.screenshot(path=os.path.join(OUT, "new-form.png"))

	res = page.evaluate(
		"""async ([customer, item]) => {
			try {
				const ins = await frappe.call({method: 'frappe.client.insert', args: {doc: {
					doctype: 'Inter Branch Sale', customer, posting_date: frappe.datetime.get_today(),
					items: [{item_code: item, qty: 1, rate: 5}]}}});
				const sub = await frappe.call({method: 'frappe.client.submit', args: {doc: ins.message}});
				return {ok: true, name: sub.message.name, se: sub.message.stock_entry, je: sub.message.journal_entry,
					amount: sub.message.total_amount, cost: sub.message.total_cost};
			} catch (e) {
				let msg = e && (e._server_messages || e.exc_type || e.message);
				try { msg = JSON.parse(e._server_messages).map(m => JSON.parse(m).message).join(' | '); } catch (_) {}
				return {ok: false, err: String(msg || JSON.stringify(e)).slice(0, 600)};
			}
		}""",
		[CUSTOMER, ITEM],
	)
	page.evaluate("frappe.ui.open_dialogs.forEach(d => d.hide()); document.querySelectorAll('.modal-backdrop').forEach(e => e.remove())")
	check("branch user can create and submit a sale", res.get("ok") and res.get("se") and res.get("je"), res)
	if res.get("ok"):
		print("SALE", res["name"])
		page.goto(f"https://{SITE}/app/inter-branch-sale/{res['name']}", wait_until="domcontentloaded")
		ready(page)
		page.wait_for_timeout(3000)
		page.screenshot(path=os.path.join(OUT, "submitted.png"))
		refused = page.evaluate("""new Promise(r => frappe.call({method: 'frappe.client.cancel',
			args: {doctype: 'Inter Branch Sale', name: %r}, error: () => r(true), callback: () => r(false)}))""" % res["name"])
		page.evaluate("frappe.ui.open_dialogs.forEach(d => d.hide()); document.querySelectorAll('.modal-backdrop').forEach(e => e.remove())")
		check("branch user cannot cancel it", refused)

	browser.close()

print("RESULT", "FAIL " + ", ".join(failed) if failed else "ALL PASS")
sys.exit(1 if failed else 0)
