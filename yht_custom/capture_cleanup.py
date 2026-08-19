"""Remove documents a capture run created on yht-khobhar. SAFE BY DEFAULT.

Run on the bench:

    bench --site yht-khobhar.enfonoerp.com execute yht_custom.capture_cleanup.report
    bench --site yht-khobhar.enfonoerp.com execute yht_custom.capture_cleanup.purge

`report` only prints. `purge` acts, and refuses anything it is not certain about.

WHY THIS IS PARANOID
A diagnostic run through `bench execute` already left one real submitted Sales Invoice
(`KSIN-26-0591`) on this client's site — `bench execute` commits, unlike `FrappeTestCase`.
This site also carries real client master data: 4,053 items, 428 customers, 2,338 sales
invoices. A cleanup that guesses is worse than no cleanup.

THE RULES, ALL OF THEM
1. Only documents owned by the capture account, created inside the window. Never anything
   else, whatever it looks like.
2. Never touch a document another document references. A Delivery Note billed by an invoice,
   an invoice with a payment against it — left alone and reported, not deleted.
3. Cancel before delete, so the GL is reversed rather than orphaned.
4. Delete children before parents: payments, then invoices, then delivery notes.
5. Re-count afterwards and print it. Do not assume the delete worked.
"""

import json

import frappe
from frappe.utils import get_datetime

CAPTURE_USER = "branchtest@yht-khobhar.enfonoerp.com"

#: Only documents created at or after this instant are candidates. Set it to just before the
#: capture run. Deliberately NOT a default of "today" — that would sweep a real day's work.
WINDOW_START = "2026-08-19 16:00:00"

#: Delete order matters: a payment references an invoice, an invoice references a delivery
#: note. Children first.
ORDER = ["Payment Entry", "Sales Invoice", "Delivery Note", "Purchase Invoice", "Quotation"]

#: Where to look for a reference back to a candidate, per doctype.
REFERRERS = {
    "Delivery Note": [
        ("Sales Invoice Item", "delivery_note"),
        ("Purchase Receipt Item", "delivery_note_item"),
    ],
    "Sales Invoice": [
        ("Payment Entry Reference", "reference_name"),
        ("Sales Invoice Item", "sales_invoice_item"),
    ],
    "Purchase Invoice": [("Payment Entry Reference", "reference_name")],
    "Quotation": [("Sales Order Item", "prevdoc_docname")],
    "Payment Entry": [],
}


def _candidates():
    out = []
    for doctype in ORDER:
        if not frappe.db.exists("DocType", doctype):
            continue
        rows = frappe.get_all(
            doctype,
            filters={"owner": CAPTURE_USER, "creation": [">=", WINDOW_START]},
            fields=["name", "docstatus", "creation"],
            order_by="creation asc",
        )
        for row in rows:
            out.append({"doctype": doctype, **row})
    return out


def _blockers(doctype, name):
    """Every document that would be orphaned by deleting this one."""
    found = []
    for child_dt, field in REFERRERS.get(doctype, []):
        if not frappe.db.exists("DocType", child_dt):
            continue
        parents = frappe.get_all(
            child_dt, filters={field: name}, fields=["parent", "parenttype"], limit=20
        )
        for row in parents:
            found.append(f"{row.parenttype or child_dt} {row.parent}")
    return sorted(set(found))


def report():
    """Print what a purge WOULD do. Changes nothing."""
    rows = _candidates()
    if not rows:
        print(f"nothing owned by {CAPTURE_USER} created since {WINDOW_START}")
        return

    print(f"{len(rows)} candidate(s) owned by {CAPTURE_USER} since {WINDOW_START}:\n")
    for row in rows:
        blockers = _blockers(row["doctype"], row["name"])
        verdict = "WOULD KEEP — referenced by " + ", ".join(blockers) if blockers else "would remove"
        print(f"  {row['doctype']:18} {row['name']:22} docstatus={row['docstatus']}  {verdict}")
    print()


def purge():
    """Cancel then delete, skipping anything referenced. Re-counts afterwards."""
    rows = _candidates()
    if not rows:
        print(f"nothing to purge for {CAPTURE_USER} since {WINDOW_START}")
        return

    removed, kept = [], []
    for row in rows:
        doctype, name = row["doctype"], row["name"]
        blockers = _blockers(doctype, name)
        if blockers:
            kept.append((doctype, name, blockers))
            continue

        try:
            doc = frappe.get_doc(doctype, name)
            if doc.docstatus == 1:
                doc.flags.ignore_permissions = True
                doc.cancel()
                frappe.db.commit()
            frappe.delete_doc(doctype, name, force=False, ignore_permissions=True)
            frappe.db.commit()
            removed.append(f"{doctype} {name}")
        except Exception as e:
            frappe.db.rollback()
            kept.append((doctype, name, [f"{type(e).__name__}: {str(e)[:90]}"]))

    print(f"removed {len(removed)}:")
    for r in removed:
        print(f"  - {r}")
    if kept:
        print(f"\nKEPT {len(kept)} — deliberately, each for a reason:")
        for doctype, name, why in kept:
            print(f"  - {doctype} {name}: {'; '.join(why)}")

    # Re-check rather than assume. A cleanup that reports success without looking is how the
    # last stray document survived unnoticed.
    left = _candidates()
    print(f"\nre-count: {len(left)} candidate(s) still present")
    for row in left:
        print(f"  ! {row['doctype']} {row['name']} docstatus={row['docstatus']}")

    print("\nGL check (company-wide, is_cancelled = 0):")
    debit, credit = frappe.db.sql(
        "SELECT COALESCE(SUM(debit),0), COALESCE(SUM(credit),0) FROM `tabGL Entry` WHERE is_cancelled = 0"
    )[0]
    print(f"  debit {debit:,.2f} vs credit {credit:,.2f} -> out by {debit - credit:,.2f}")
    print("  (a pre-existing SAR 3,000.00 imbalance is expected — KS-JV-26-0074)")
