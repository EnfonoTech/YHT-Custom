"""Real-browser check of the client's answers of 2026-10-27 (Q5 no quick customer, Q6 print preview).

    SID_FILE=/path/sid.txt SITE=yht-test.enfonoerp.com python3 ui_check_1027_answers.py [outdir]

Same contract as `ui_check_1027.py`: a server-minted session, the file 0600, the session revoked afterwards.
It only reads: forms are opened and never saved, `window.open` is stubbed so no print is generated, and the
one server call it makes is refused by design.
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


def ready(page):
	page.wait_for_function("window.frappe && frappe.session && frappe.session.user !== 'Guest'", timeout=60000)


def open_new(page, doctype):
	slug = doctype.lower().replace(" ", "-")
	page.goto(f"https://{SITE}/app/{slug}/new", wait_until="domcontentloaded")
	ready(page)
	page.wait_for_function(f"location.pathname.includes('/new-{slug}-')", timeout=30000)
	page.wait_for_load_state("domcontentloaded")
	page.wait_for_function(f"window.cur_frm && cur_frm.doctype === '{doctype}'", timeout=60000)
	page.wait_for_timeout(2500)


with sync_playwright() as p:
	browser = p.chromium.launch(headless=True)
	ctx = browser.new_context(viewport={"width": 1500, "height": 1000})
	ctx.add_cookies([{"name": "sid", "value": SID, "domain": SITE, "path": "/", "secure": True, "httpOnly": True, "sameSite": "Lax"}])
	page = ctx.new_page()
	page.set_default_timeout(45000)

	page.goto(f"https://{SITE}/app", wait_until="domcontentloaded")
	ready(page)
	print("USER", page.evaluate("frappe.session.user"))
	feats = page.evaluate("frappe.boot.yht_features || []")
	check("boot carries both switches", "oct27_no_quick_customer" in feats and "oct27_print_preview" in feats)

	# --- Q5 ------------------------------------------------------------------
	for dt in ("Sales Invoice", "Quotation"):
		open_new(page, dt)
		n = page.evaluate("document.querySelectorAll('.yht-create-customer-btn').length")
		check(f"{dt}: no Create New Customer button", n == 0, n)
		page.screenshot(path=os.path.join(OUT, dt.lower().replace(" ", "-") + "-no-quick-customer.png"))

	qe = page.evaluate("new Promise(r => frappe.model.with_doctype('Customer', () => r(frappe.get_meta('Customer').quick_entry)))")
	check("Customer quick entry is off", not qe, qe)

	refused = page.evaluate("""new Promise(r => frappe.call({
		method: 'yht_custom.api.customer.create_customer_with_address',
		args: {customer_name: 'ZQXTEST ui quick customer', mobile_no: '0500000000'},
		error: () => r(true), callback: () => r(false)}))""")
	page.evaluate("frappe.ui.open_dialogs.forEach(d => d.hide()); document.querySelectorAll('.modal-backdrop').forEach(e => e.remove())")
	check("quick-create endpoint refuses", refused)

	page.goto(f"https://{SITE}/app/yht-dashboard", wait_until="domcontentloaded")
	ready(page)
	page.wait_for_selector("[data-yht-dialog='Customer']", timeout=30000)
	page.evaluate("document.querySelector(\"[data-yht-dialog='Customer']\").click()")
	page.wait_for_timeout(4000)
	path = page.evaluate("location.pathname")
	dialogs = page.evaluate("frappe.ui.open_dialogs.length")
	check("dashboard New Customer tile opens the full Customer form", "/app/customer/new-customer-" in path and dialogs == 0, f"{path} dialogs={dialogs}")
	page.screenshot(path=os.path.join(OUT, "customer-full-form.png"))

	# --- Q6 ------------------------------------------------------------------
	name = page.evaluate("""new Promise(r => frappe.db.get_list('Sales Invoice',
		{filters: {docstatus: 1, is_return: 0}, fields: ['name'], limit: 1, order_by: 'creation desc'}).then(x => r(x.length ? x[0].name : null)))""")
	check("a submitted Sales Invoice to print", bool(name), name)
	if name:
		page.goto(f"https://{SITE}/app/sales-invoice/{name}", wait_until="domcontentloaded")
		ready(page)
		page.wait_for_function(f"window.cur_frm && cur_frm.doc.name === '{name}'", timeout=60000)
		page.wait_for_timeout(2500)
		# Ends in `; 0`: Playwright CALLS an expression whose value is a function, which would invoke the stub.
		page.evaluate("window.__opened = []; window.open = (u) => { window.__opened.push(u); return null; }; 0")
		labels = page.evaluate("[...document.querySelectorAll('.page-actions button, .custom-actions button')].map(b => b.innerText.trim()).filter(Boolean)")
		# "Print PDF" on the legacy set, "Print" once the set is consolidated (rows 17 + 34): same handler.
		clicked = page.evaluate("""(() => {
			const b = [...document.querySelectorAll('.custom-actions button')]
				.find(x => ['Print PDF', 'Print'].includes(x.innerText.trim()) && !x.closest('.dropdown-menu'));
			if (!b) return null; b.click(); return b.innerText.trim() + ' ' + b.className; })()""")
		check("toolbar print button present", bool(clicked), labels)
		if clicked:
			page.wait_for_timeout(1000)
			opened = page.evaluate("window.__opened")
			url = (opened[0] if opened else "") or ""

			check("Print PDF opens /printview", url.startswith("/printview?"), url)
			check("…with the browser print dialog", "trigger_print=1" in url, url)
			check("…and not the server PDF", "download_pdf" not in url, url)

	browser.close()

print("RESULT", "FAIL" if failed else "PASS", len(failed))
sys.exit(1 if failed else 0)
