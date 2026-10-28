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
| Stock Entry (Material Issue) | Dr **Cost of Goods Sold** / Cr Stock, at cost |
| Journal Entry | Dr **Receivable** (party = the customer) / Cr **Sales Income**, at selling price |

**Redesigned 2026-10-27 (user decision: "mirror the Sales Invoice"):** the same GL a Sales Invoice with Update Stock
posts, minus the VAT row. The 10-19 version's Clearing and Margin accounts are gone; the margin is simply income minus
COGS, as for any sale. `total_cost` / `margin` on the document are read back from the Stock Ledger. Cancel reverses the
Journal Entry, then the Stock Entry.

## Setup (Inter Branch Sale Settings) — nothing submits until all of it is set

1. Company, Receivable Account (Receivable type), Cost of Goods Sold Account (Expense), Sales Income Account (Income), Cost Center.
2. Optional defaults: price list, source warehouse.
3. The customers allowed. Create each as a normal Customer first (tick **Is Internal Customer**).

**Decided by the client (Osaid, WhatsApp 2026-10-28):** "all normal accounts as sales only VAT will be excluded in the
entries". So the Sales Income and Cost of Goods Sold accounts are the company's normal ones (on this site the Company's
Default Income Account and Default Cost of Goods Sold Account), and no VAT row is posted. Still set in the Settings form,
not in code, so the accountant can change them without a deploy.

## Gate

`yht_features` must contain `oct19_inter_branch_sale` (or `all`), else the document refuses to save. An unset switch
does NOT keep the doctype off a site: the DocType arrives with the next `migrate` on any site, which is why the branch is held.

## Not built (phase 2)

Returns (cancel works), a print format, a report, Branch User permissions and branch scoping (roles today: Stock
Manager, Sales Manager, Accounts Manager, System Manager), a payable side (not needed while the receivers keep their own books).

## Tests and UAT (2026-10-19)

`yht_custom/tests/test_inter_branch_sale.py`: **22 of 22 pass on yht-test**, including the real Stock Entry and Journal Entry,
cancel, and the refusals. Run with `--skip-before-tests` (see memory `bench-run-tests-deletes-item-price`).

Demo on yht-test (placeholders, NOT the accountant's choice): Receivable `1004001 - CUSTOMERS - RECEIVABLES - KATC`,
Clearing `Inter-Branch Clearing - KATC`, Margin `Inter-Branch Margin - KATC`, customers CU0022 and CU0419; documents
`KSIB-26-0001..0006`. Video: `docs/inter-branch-sale-demo-2026-10-19.mp4` (outside the repo, in the YHT Trading folder).

The box was checked out onto this branch for the run and restored to `pipeline/meeting-1011-wednesday`. yht-test now holds the
doctypes without the code: do not migrate it while the box is on the deploy branch (memory `held-feature-doctypes-orphaned-on-yht-test`).

## To test again

Check the branch out on the box (SHA-gated), `reload_doc` the four doctypes on yht-test, QUIT the web workers, run the module,
then restore the deploy branch. Never migrate live while it is checked out.
