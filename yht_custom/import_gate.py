# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""The import gate — plan step 7.1, the MoM's agreed acceptance test.

The MoM's test is "the trial balance matches and stock ties to GL". Today the
SOURCE data fails that test, so this exists to be run twice: once on the incumbent
data before cut-over, once after the import, with the same numbers coming out both
times or a documented reason why not.

MEASURED ON THIS SITE, 2026-08-20 — every figure below is a live measurement, and
every one of them matches what `docs/00-STUDY-AND-PLAN.md` §2.4 recorded:

    GL debit 70,254,978.90 vs credit 70,251,978.90     out by SAR 3,000.00
    Bin stock value 1,215,757.78 vs Stock In Hand GL 1,141,348.51
                                                      out by SAR 74,409.27
    102 bins with negative qty, 1 with negative value
    26 bins holding qty at a zero valuation rate, 55 SLE rows likewise
    stock_frozen_upto and acc_frozen_upto both 0001-01-01

ONE CHECK I GOT WRONG FIRST, WORTH THE WARNING. Comparing `Bin.actual_qty` against
`SUM(Stock Ledger Entry.actual_qty)` reported 1,863 of 2,820 bins as broken. It is
the wrong basis: this site has **3,469 Stock Reconciliation SLE rows and every one
carries `actual_qty = 0`**, because a reconciliation sets `qty_after_transaction`
absolutely rather than posting a movement. Against the correct basis — the LATEST
SLE's `qty_after_transaction` and `stock_value` — **0 of 2,820 bins disagree**.

That negative result matters: the stock subsystem agrees with itself, so the
SAR 74,409.27 gap is between stock and the GL, not inside the stock ledger.
"""

import json
import os

import frappe
from frappe import _
from frappe.utils import cstr, flt, get_site_path

#: Money tolerance, SAR. Below this two paths are "the same number".
TOLERANCE = 0.05

#: The account stock is expected to tie to. Resolved by name so a renamed chart
#: does not silently make the check pass by finding nothing.
STOCK_ACCOUNT_LIKE = "%Stock In Hand%"

#: Where pre/post snapshots live.
SNAPSHOT_DIR = "import-gate"


# --------------------------------------------------------------------- checks


def _gl_balanced():
	row = frappe.db.sql(
		"""SELECT ROUND(SUM(debit), 2) dr, ROUND(SUM(credit), 2) cr
		   FROM `tabGL Entry` WHERE is_cancelled = 0""",
		as_dict=True,
	)[0]
	diff = flt(row.dr) - flt(row.cr)
	return {
		"measured": f"Dr {flt(row.dr):,.2f} / Cr {flt(row.cr):,.2f}",
		"difference": diff,
		"detail": _worst_unbalanced_voucher() if abs(diff) > TOLERANCE else "",
	}


def _worst_unbalanced_voucher():
	rows = frappe.db.sql(
		"""SELECT voucher_type, voucher_no, ROUND(SUM(debit) - SUM(credit), 2) d
		   FROM `tabGL Entry` WHERE is_cancelled = 0
		   GROUP BY voucher_type, voucher_no
		   HAVING ABS(SUM(debit) - SUM(credit)) > 0.005
		   ORDER BY ABS(SUM(debit) - SUM(credit)) DESC LIMIT 3""",
		as_dict=True,
	)
	return ", ".join(f"{r.voucher_no} ({flt(r.d):,.2f})" for r in rows)


def _voucher_level_balance():
	"""A GL that balances in total can still hold offsetting broken vouchers."""
	rows = frappe.db.sql(
		"""SELECT COUNT(*) n FROM (
		     SELECT voucher_no FROM `tabGL Entry` WHERE is_cancelled = 0
		     GROUP BY voucher_type, voucher_no
		     HAVING ABS(SUM(debit) - SUM(credit)) > 0.005) t""",
		as_dict=True,
	)[0]
	return {"measured": f"{rows.n} voucher(s)", "difference": flt(rows.n), "detail": _worst_unbalanced_voucher()}


def _accounting_equation():
	"""Assets = Liabilities + Equity + (Income − Expense).

	An independent route to the same answer as the debit/credit total: if the two
	disagree about the size of the hole, one of them is measuring the wrong thing.
	"""
	row = frappe.db.sql(
		"""SELECT
		     ROUND(SUM(CASE WHEN a.root_type = 'Asset'     THEN gl.debit - gl.credit ELSE 0 END), 2) assets,
		     ROUND(SUM(CASE WHEN a.root_type = 'Liability' THEN gl.credit - gl.debit ELSE 0 END), 2) liabilities,
		     ROUND(SUM(CASE WHEN a.root_type = 'Equity'    THEN gl.credit - gl.debit ELSE 0 END), 2) equity,
		     ROUND(SUM(CASE WHEN a.root_type = 'Income'    THEN gl.credit - gl.debit ELSE 0 END), 2) income,
		     ROUND(SUM(CASE WHEN a.root_type = 'Expense'   THEN gl.debit - gl.credit ELSE 0 END), 2) expense
		   FROM `tabGL Entry` gl INNER JOIN `tabAccount` a ON a.name = gl.account
		   WHERE gl.is_cancelled = 0""",
		as_dict=True,
	)[0]
	right = flt(row.liabilities) + flt(row.equity) + flt(row.income) - flt(row.expense)
	diff = flt(row.assets) - right
	return {
		"measured": f"Assets {flt(row.assets):,.2f} vs {right:,.2f}",
		"difference": diff,
		"detail": (
			f"L {flt(row.liabilities):,.2f} + E {flt(row.equity):,.2f} "
			f"+ (I {flt(row.income):,.2f} − X {flt(row.expense):,.2f})"
		),
	}


def _stock_ties_to_gl():
	bin_value = flt(
		frappe.db.sql("SELECT ROUND(SUM(stock_value), 2) FROM `tabBin`")[0][0]
	)
	account = frappe.db.sql(
		"SELECT name FROM `tabAccount` WHERE name LIKE %s LIMIT 1", (STOCK_ACCOUNT_LIKE,)
	)
	if not account:
		return {
			"measured": "no Stock In Hand account found",
			"difference": None,
			"detail": "the check cannot run — do not read this as a pass",
		}

	gl_value = flt(
		frappe.db.sql(
			"""SELECT ROUND(SUM(debit) - SUM(credit), 2) FROM `tabGL Entry`
			   WHERE is_cancelled = 0 AND account = %s""",
			(account[0][0],),
		)[0][0]
	)
	return {
		"measured": f"Bin {bin_value:,.2f} vs GL {gl_value:,.2f}",
		"difference": bin_value - gl_value,
		"detail": account[0][0],
	}


def _bin_agrees_with_ledger():
	"""Bin against the LATEST SLE, not the SUM of movements.

	`SUM(actual_qty)` is the wrong basis wherever Stock Reconciliations exist: this
	site has 3,469 reconciliation rows, all with `actual_qty = 0`, because a
	reconciliation sets `qty_after_transaction` absolutely. That mistake reported
	1,863 broken bins where there are none.

	The columns are compared directly rather than through a SELECT alias: an alias
	is not visible to the WHERE of the same query, which raised "Unknown column
	's.sle_value' in 'WHERE'". The runner reported that as ERROR rather than
	silently passing the check, which is the only reason it was caught.
	"""
	rows = frappe.db.sql(
		"""SELECT COUNT(*) n
		   FROM `tabBin` b
		   INNER JOIN `tabStock Ledger Entry` s ON s.name = (
		     SELECT s2.name FROM `tabStock Ledger Entry` s2
		     WHERE s2.item_code = b.item_code AND s2.warehouse = b.warehouse
		       AND s2.is_cancelled = 0
		     ORDER BY s2.posting_datetime DESC, s2.creation DESC LIMIT 1)
		   WHERE ABS(b.actual_qty - s.qty_after_transaction) > 0.001
		      OR ABS(b.stock_value - s.stock_value) > 0.05""",
		as_dict=True,
	)[0]
	total = frappe.db.count("Bin")
	return {"measured": f"{rows.n} of {total} bins disagree", "difference": flt(rows.n), "detail": ""}


def _no_negative_stock():
	rows = frappe.db.sql(
		"""SELECT item_code, warehouse, actual_qty FROM `tabBin`
		   WHERE actual_qty < 0 ORDER BY actual_qty ASC LIMIT 3""",
		as_dict=True,
	)
	count = frappe.db.count("Bin", {"actual_qty": ["<", 0]})
	return {
		"measured": f"{count} bin(s)",
		"difference": flt(count),
		"detail": ", ".join(f"{r.item_code} @ {flt(r.actual_qty):,.0f}" for r in rows),
	}


def _no_negative_stock_value():
	count = frappe.db.count("Bin", {"stock_value": ["<", 0]})
	return {"measured": f"{count} bin(s)", "difference": flt(count), "detail": ""}


def _no_zero_value_stock():
	rows = frappe.db.sql(
		"""SELECT item_code, warehouse, actual_qty FROM `tabBin`
		   WHERE actual_qty > 0 AND (valuation_rate = 0 OR valuation_rate IS NULL)
		   ORDER BY actual_qty DESC LIMIT 3""",
		as_dict=True,
	)
	count = frappe.db.sql(
		"""SELECT COUNT(*) FROM `tabBin`
		   WHERE actual_qty > 0 AND (valuation_rate = 0 OR valuation_rate IS NULL)"""
	)[0][0]
	sle = frappe.db.sql(
		"""SELECT COUNT(*) FROM `tabStock Ledger Entry`
		   WHERE is_cancelled = 0 AND actual_qty > 0
		     AND (valuation_rate = 0 OR valuation_rate IS NULL)"""
	)[0][0]
	return {
		"measured": f"{count} bin(s), {sle} ledger row(s)",
		"difference": flt(count),
		"detail": ", ".join(f"{r.item_code} qty {flt(r.actual_qty):,.0f}" for r in rows),
	}


def _valuation_method_uniform():
	configured = frappe.db.get_single_value("Stock Settings", "valuation_method")
	rows = frappe.db.sql(
		"""SELECT COALESCE(NULLIF(valuation_method, ''), '(blank)') method, COUNT(*) n
		   FROM `tabItem` WHERE is_stock_item = 1 GROUP BY method ORDER BY n DESC""",
		as_dict=True,
	)
	off = sum(r.n for r in rows if r.method != configured)
	return {
		"measured": f"{off} item(s) not on {configured}",
		"difference": flt(off),
		"detail": ", ".join(f"{r.method} {r.n}" for r in rows),
	}


def _periods_frozen():
	stock = cstr(frappe.db.get_single_value("Stock Settings", "stock_frozen_upto"))
	accounts = cstr(frappe.db.get_single_value("Accounts Settings", "acc_frozen_upto"))
	unset = [
		label
		for label, value in (("stock", stock), ("accounts", accounts))
		if not value or value.startswith("0001-01-01")
	]
	return {
		"measured": f"stock {stock or 'unset'}, accounts {accounts or 'unset'}",
		"difference": flt(len(unset)),
		"detail": "set both at go-live (B15)" if unset else "",
	}


def _no_test_accounts():
	"""A capture/UAT account must not survive go-live.

	`branchtest@yht-khobhar.enfonoerp.com` has been flagged "disable before
	go-live" in the handoff for four sessions running. It is deliberately still
	ENABLED — client UAT (step 7.4) has not happened yet and disabling it would
	block the very testing it exists for — so instead of another checklist line
	nobody reads, the go-live gate refuses while it is enabled.
	"""
	accounts = frappe.get_all(
		"User",
		filters={"enabled": 1, "name": ["like", "%branchtest%"]},
		pluck="name",
	)
	accounts += frappe.get_all(
		"User",
		filters={"enabled": 1, "name": ["like", "_test%"]},
		pluck="name",
	)
	accounts = sorted(set(accounts))
	return {
		"measured": f"{len(accounts)} enabled",
		"difference": flt(len(accounts)),
		"detail": ", ".join(accounts[:4]) + (" — keep for UAT, disable at go-live" if accounts else ""),
	}


#: (key, label, function, blocking). `blocking` means go-live must not proceed
#: while it fails; the rest are recorded and signed off.
CHECKS = (
	("gl_balanced", "GL balances", _gl_balanced, True),
	("gl_voucher_balanced", "Every voucher balances", _voucher_level_balance, True),
	("accounting_equation", "Accounting equation holds", _accounting_equation, True),
	("stock_ties_to_gl", "Stock value ties to GL", _stock_ties_to_gl, True),
	("bin_agrees_with_ledger", "Bins agree with the stock ledger", _bin_agrees_with_ledger, True),
	("no_negative_stock", "No negative stock", _no_negative_stock, True),
	("no_negative_stock_value", "No negative stock value", _no_negative_stock_value, True),
	("no_zero_value_stock", "No stock held at zero value", _no_zero_value_stock, False),
	("valuation_method_uniform", "One valuation method", _valuation_method_uniform, False),
	("periods_frozen", "Periods frozen", _periods_frozen, False),
	("no_test_accounts", "No test accounts enabled", _no_test_accounts, True),
)


def run_checks() -> list[dict]:
	"""Every check, in order, with a verdict. Read-only."""
	results = []
	for key, label, func, blocking in CHECKS:
		try:
			outcome = func()
			difference = outcome.get("difference")
			if difference is None:
				status = "ERROR"
			else:
				status = "PASS" if abs(flt(difference)) <= TOLERANCE else "FAIL"
		except Exception as e:
			outcome = {"measured": "", "difference": None, "detail": f"{type(e).__name__}: {e}"}
			status = "ERROR"
			frappe.log_error(frappe.get_traceback(), f"import gate: {key}")

		results.append(
			{
				"key": key,
				"check": label,
				"status": status,
				"blocking": 1 if blocking else 0,
				"measured": outcome.get("measured"),
				"difference": outcome.get("difference"),
				"detail": outcome.get("detail"),
			}
		)
	return results


def gate_passes() -> bool:
	"""True only when every BLOCKING check passes. Nothing else counts."""
	return not [r for r in run_checks() if r["blocking"] and r["status"] != "PASS"]


@frappe.whitelist()
def summary():
	"""Callable from the desk. Read-only, so `read` on Bin is enough."""
	frappe.only_for(("System Manager", "Accounts Manager", "Stock Manager"))
	results = run_checks()
	return {
		"passes": not [r for r in results if r["blocking"] and r["status"] != "PASS"],
		"checks": results,
	}


def run():
	"""Print the gate. `bench --site … execute yht_custom.import_gate.run`"""
	results = run_checks()
	width = max(len(r["check"]) for r in results)
	print("")
	for row in results:
		flag = "!" if row["blocking"] else " "
		print(f"  {row['status']:<5}{flag} {row['check']:<{width}}  {row['measured']}")
		if row["detail"]:
			print(f"        {' ' * width}  {row['detail']}")
	blocking_failures = [r for r in results if r["blocking"] and r["status"] != "PASS"]
	print("")
	print(f"  GATE: {'PASS' if not blocking_failures else 'FAIL'}"
	      f" — {len(blocking_failures)} blocking failure(s)")
	return results


# ------------------------------------------------------------------ snapshots


def snapshot() -> list[dict]:
	"""Per item, per warehouse: qty, valuation rate, value — the MoM deliverable.

	Taken from Bin, with the latest ledger row alongside so a pre/post comparison
	can show whether the import moved the balance or only the bookkeeping.
	"""
	return frappe.db.sql(
		"""SELECT b.item_code, b.warehouse, b.actual_qty, b.valuation_rate, b.stock_value,
		          i.item_name, i.item_group,
		          s.qty_after_transaction AS ledger_qty, s.stock_value AS ledger_value,
		          s.posting_date AS ledger_date
		   FROM `tabBin` b
		   LEFT JOIN `tabItem` i ON i.name = b.item_code
		   LEFT JOIN `tabStock Ledger Entry` s ON s.name = (
		     SELECT s2.name FROM `tabStock Ledger Entry` s2
		     WHERE s2.item_code = b.item_code AND s2.warehouse = b.warehouse
		       AND s2.is_cancelled = 0
		     ORDER BY s2.posting_datetime DESC, s2.creation DESC LIMIT 1)
		   ORDER BY b.item_code, b.warehouse""",
		as_dict=True,
	)


def _snapshot_path(label: str) -> str:
	folder = get_site_path("private", "files", SNAPSHOT_DIR)
	os.makedirs(folder, exist_ok=True)
	safe = "".join(c for c in cstr(label) if c.isalnum() or c in "-_")
	if not safe:
		frappe.throw(_("Give the snapshot a name"))
	return os.path.join(folder, f"{safe}.json")


def save_snapshot(label: str) -> str:
	"""Write a named snapshot. Run one BEFORE the import and one after."""
	rows = snapshot()
	path = _snapshot_path(label)
	with open(path, "w") as handle:
		json.dump({"label": label, "rows": rows}, handle, default=str)
	print(f"  {len(rows)} rows -> {path}")
	return path


def compare_snapshots(before: str, after: str) -> dict:
	"""Per-item qty and value movement between two snapshots.

	This is the pre/post acceptance test. A revaluation is supposed to move Stock in
	Hand, COGS and Net Profit and NOTHING else — so an item that changes VALUE while
	its QTY is unchanged is the interesting case, and it is reported separately.
	"""
	def load(label):
		with open(_snapshot_path(label)) as handle:
			data = json.load(handle)
		return {(r["item_code"], r["warehouse"]): r for r in data["rows"]}

	old, new = load(before), load(after)
	keys = set(old) | set(new)

	qty_moved, value_only, appeared, vanished = [], [], [], []
	for key in sorted(keys):
		a, b = old.get(key), new.get(key)
		if not a:
			appeared.append(key)
			continue
		if not b:
			vanished.append(key)
			continue
		dq = flt(b["actual_qty"]) - flt(a["actual_qty"])
		dv = flt(b["stock_value"]) - flt(a["stock_value"])
		if abs(dq) > 0.001:
			qty_moved.append({"key": key, "qty_delta": dq, "value_delta": dv})
		elif abs(dv) > TOLERANCE:
			value_only.append({"key": key, "value_delta": dv})

	result = {
		"rows_before": len(old),
		"rows_after": len(new),
		"qty_changed": len(qty_moved),
		"value_changed_only": len(value_only),
		"appeared": len(appeared),
		"vanished": len(vanished),
		"total_value_before": sum(flt(r["stock_value"]) for r in old.values()),
		"total_value_after": sum(flt(r["stock_value"]) for r in new.values()),
	}
	result["total_value_delta"] = result["total_value_after"] - result["total_value_before"]
	print(frappe.as_json(result, indent=1))
	return result
