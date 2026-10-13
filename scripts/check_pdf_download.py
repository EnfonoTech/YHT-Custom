# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
#
# Usage (from the bench's `sites/` directory, as the bench user):
#   sudo -u v15 -H env YHT_SITE=yht-test ../env/bin/python -I /path/to/check_pdf_download.py
#
# 🔴 THE REAL-PATH CHECK for the KATC PDF download (print_download.py). A PDF made in a script has no
# request, so no `before_request` hook and never shows the 417 that Print Designer's hook caused;
# only the HTTP endpoint does. This mints a short-lived Administrator session server-side (no
# password involved), asks /api/method/frappe.utils.print_format.download_pdf for every enabled
# KATC format over HTTPS, prints status / type / size / page count, and revokes the session.
# Every line must read `200 application/pdf` - anything else is a failure.
import os, sys, subprocess, json
SITE = os.environ["YHT_SITE"]
import frappe
frappe.init(site=SITE, sites_path="/home/v15/yht-bench/sites"); frappe.connect()
frappe.local.form_dict = frappe._dict({"sid": "Guest"})
user = frappe.get_doc("User", "Administrator")
session = frappe.sessions.Session(user="Administrator", resume=False, full_name=user.full_name, user_type=user.user_type)
frappe.db.commit()
sid = session.sid
rows = []
try:
    fmts = frappe.get_all("Print Format", filters={"disabled": 0, "name": ["like", "KATC%"]}, fields=["name", "doc_type", "pdf_generator"], order_by="name")
    host = SITE if "." in SITE else SITE + ".enfonoerp.com"
    for f in fmts:
        name = frappe.db.get_value(f.doc_type, {"docstatus": 1}, "name", order_by="modified desc")
        url = f"https://{host}/api/method/frappe.utils.print_format.download_pdf"
        out = f"/tmp/pdfcheck-{f.name.replace(' ','_')}.pdf"
        r = subprocess.run(["curl","-s","-G","-o",out,"-w","%{http_code} %{content_type} %{size_download}","-b",f"sid={sid}","--data-urlencode",f"doctype={f.doc_type}","--data-urlencode",f"name={name}","--data-urlencode",f"format={f.name}","--data-urlencode","no_letterhead=0",url],capture_output=True,text=True)
        head = open(out,"rb").read(5) if os.path.exists(out) else b""
        pages = ""
        if head.startswith(b"%PDF"):
            from pypdf import PdfReader
            pages = f"pages={len(PdfReader(out).pages)}"
        else:
            pages = open(out,errors="replace").read()[:160].replace("\n"," ") if os.path.exists(out) else ""
        print(f"{f.name:28} gen={f.pdf_generator or '-':20} {f.doc_type:15} {name:14} -> {r.stdout.strip()} {pages}")
        os.path.exists(out) and os.remove(out)
finally:
    frappe.db.delete("Sessions", {"sid": sid}); frappe.db.commit()
    try: frappe.cache.hdel("session", sid)
    except Exception: pass
    print("session revoked:", not frappe.db.exists("Sessions", {"sid": sid}))
frappe.destroy()
