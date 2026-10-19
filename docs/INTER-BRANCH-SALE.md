# Inter Branch Sale — HELD (2026-10-19)

Branch `feature/inter-branch-sale`, cut from `40f4bdd`. **Not agreed with the client. Not on the deploy branch
`pipeline/meeting-1011-wednesday`. Never merge, cherry-pick or push it there without the user's explicit go.**
See memory `unagreed-features-stay-off-the-deploy-branch`.

## What it is

Stock sold to another group entity that keeps its own books (Jeddah, Jubail, Yanbu, Al Badr, Waqt Al Enjaz: customers
carrying the company's VAT number, not branches of this site), at a **selling price**, **without a Sales Invoice**, so
nothing is reported to ZATCA. One submittable doctype, **Inter Branch Sale** (series `KSIB-YY-####`).

On submit, one transaction:

| Document | Posts |
|---|---|
| Stock Entry (Material Issue) | stock out at cost; the debit goes to the **Inter-Branch Clearing** account |
| Journal Entry | Dr **Receivable** (party = the customer) at selling price; Cr **Clearing** at cost; the difference to the **Margin** account (a debit when sold below cost) |

Net: receivable at selling price, stock out at cost, margin booked, Clearing nets to zero. The cost is read from the
Stock Ledger the Stock Entry wrote, so the Journal Entry always matches the stock value. Cancel reverses the Journal
Entry, then the Stock Entry.

## Setup (Inter Branch Sale Settings) — nothing submits until all of it is set

1. Company, Receivable Account (Receivable type), Clearing Account (Balance Sheet), Margin Account (Income), Cost Center.
2. Optional defaults: price list, source warehouse.
3. The customers allowed. Create each as a normal Customer first (tick **Is Internal Customer**).

**Open, for the client's accountant (nothing is defaulted in code):** which account carries the receivable; which account
takes the margin (an internal recharge, **not turnover**, so exclude it from revenue reports); whether any VAT applies
(assumed none, the customers carry the company's own VAT number); whether selling above cost is right at all.

## Gate

`yht_features` must contain `oct19_inter_branch_sale` (or `all`), else the document refuses to save. An unset switch
does NOT keep the doctype off a site: the DocType arrives with the next `migrate` on any site, which is why the branch is held.

## Not built (phase 2)

Returns (cancel works), a print format, a report, Branch User permissions and branch scoping (roles today: Stock
Manager, Sales Manager, Accounts Manager, System Manager), a payable side (not needed while the receivers keep their own books).

## Tests

`yht_custom/tests/test_inter_branch_sale.py`. The pure parts (posting arithmetic, structure, settings gaps) pass under a
stub locally. `TestEndToEnd` (real Stock Entry + Journal Entry, cancel, refusals) has **not been run on a site**: it needs the
branch checked out on the box, which is allowed only on the user's say-so (live and UAT share one apps directory).

## To test on yht-test later

Check the branch out on the box for the run and restore the deploy branch afterwards; `bench --site yht-test migrate`
(live must NOT migrate while it is checked out), set `yht_features` to `["all"]` on yht-test (already so), then run the module.
