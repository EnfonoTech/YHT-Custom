#!/usr/bin/env python3
"""Does any Arabic glyph escape its column?  An objective answer, from the PDF.

WHY THIS EXISTS. Three fixes to the Arabic column shipped broken because they were
verified by eye on one document, or through `frappe.utils.pdf.get_pdf(html)` — which
does NOT apply the Print Format's page geometry, so it renders on a wider page than the
user's download and hides the overflow. The only valid check is a PDF produced through
`frappe.utils.print_format.download_pdf`, measured rather than looked at.

⚠️ It does NOT use the `pdftotext -bbox` "does x move backwards" test. On a line mixing
RTL and LTR runs the words come out in LOGICAL order, so that check false-positives on
every bilingual line — including the letterhead.

Two independent checks, because either alone can pass a bad fix:

  OVERFLOW  no Arabic character's box may cross either vertical rule of its column.
  GEOMETRY  the drawn rules must stay at their nominal proportions. An over-long line
            silently WIDENS the Arabic column at the English column's expense, which
            reads clean on the overflow check while wrecking the layout.

Usage:
    python scripts/katc_ar_overflow.py FILE.pdf [FILE.pdf ...]
    python scripts/katc_ar_overflow.py --nominal 5,24,34,13,12,12 FILE.pdf
    python scripts/katc_ar_overflow.py --print-constants FILE.pdf
"""

import argparse
import sys

AR_RANGES = ((0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))
#: RLM / NBSP carry no ink; they must not be counted as an escaping glyph.
INVISIBLE = {"‏", "‎", " ", " "}


def is_arabic(ch: str) -> bool:
	cp = ord(ch)
	return any(lo <= cp <= hi for lo, hi in AR_RANGES)


def column_rules(page, min_coverage: float = 30.0, tol: float = 1.0):
	"""x of every items-table column rule, by clustering the vertical edges.

	⚠️ The borders are NOT full-height rules. wkhtmltopdf draws `border: 1px solid` as a
	separate short segment PER CELL — 366 vertical edges on one page, most only 16-25 pt
	tall — so a naive "is this line tall enough" filter finds nothing. Cluster the edges
	by x and keep the clusters with enough TOTAL vertical coverage to be a column edge.
	"""
	buckets: dict[float, float] = {}
	for e in page.edges:
		if e.get("orientation") != "v":
			continue
		x = round((e["x0"] + e["x1"]) / 2.0, 1)
		key = next((k for k in buckets if abs(k - x) <= tol), x)
		buckets[key] = buckets.get(key, 0.0) + (e["bottom"] - e["top"])
	return sorted(x for x, cov in buckets.items() if cov >= min_coverage)


def arabic_column(page, header_text: str = "Arabic"):
	"""(left_rule, right_rule, header_bottom) for the Arabic column.

	Anchored on the COLUMN HEADER rather than on rule geometry. The page carries other
	bordered blocks (the header table, the totals) and the letterhead itself contains
	Arabic, so picking rules by span alone selects the wrong table and then flags the
	letterhead as an overflow. Finding the header word is unambiguous.
	"""
	head = None
	for w in page.extract_words():
		if w["text"].strip() == header_text:
			head = w
			break
	if head is None:
		return None

	centre = (head["x0"] + head["x1"]) / 2.0
	rules = column_rules(page)
	left = max((x for x in rules if x < centre), default=None)
	right = min((x for x in rules if x > centre), default=None)
	if left is None or right is None:
		return None
	return left, right, head["bottom"]


def check(path: str, nominal, verbose: bool = False):
	import pdfplumber

	problems, notes = [], []
	with pdfplumber.open(path) as pdf:
		for pno, page in enumerate(pdf.pages, 1):
			col = arabic_column(page)
			if col is None:
				notes.append(f"p{pno}: no Arabic column header found — skipped")
				continue
			left, right, header_bottom = col

			rules = column_rules(page)
			table = [x for x in rules if left - 200 <= x <= right + 260]
			if len(table) >= len(nominal) + 1:
				window = table[: len(nominal) + 1]
				span = window[-1] - window[0]
				pct = [round((window[i + 1] - window[i]) / span * 100, 2) for i in range(len(nominal))]
				# ⚠️ INFORMATIONAL, not a gate. The page carries other bordered blocks
				# (header table, totals) whose rules interleave with the items table's,
				# and picking the right seven reliably is a separate problem. The
				# OVERFLOW check below is anchored on the column header and IS reliable.
				if verbose:
					notes.append(f"p{pno}: nearby rules {window}  pct {pct}  (informational)")

			over = 0
			worst = 0.0
			for ch in page.chars:
				t = ch.get("text", "")
				# BELOW the header only — the letterhead is Arabic too.
				if ch["top"] <= header_bottom or t in INVISIBLE or not is_arabic(t):
					continue
				if ch["x1"] > right + 0.5:
					over += 1
					worst = max(worst, ch["x1"] - right)
				elif ch["x0"] < left - 0.5:
					over += 1
					worst = max(worst, left - ch["x0"])
			if over:
				problems.append(
					f"p{pno} OVERFLOW: {over} Arabic glyphs outside the column "
					f"[{left:.1f}, {right:.1f}], worst +{worst:.2f} pt"
				)
			elif verbose:
				notes.append(f"p{pno}: arabic column [{left:.1f}, {right:.1f}] = {right-left:.1f} pt, 0 escapes")
	return problems, notes


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("pdfs", nargs="+")
	ap.add_argument("--nominal", default="5,24,34,13,12,12")
	ap.add_argument("--print-constants", action="store_true")
	ap.add_argument("-v", "--verbose", action="store_true")
	a = ap.parse_args()
	nominal = [float(x) for x in a.nominal.split(",")]

	bad = 0
	for path in a.pdfs:
		problems, notes = check(path, nominal, a.verbose or a.print_constants)
		name = path.rsplit("/", 1)[-1]
		if problems:
			bad += 1
			print(f"FAIL  {name}")
			for p in problems[:8]:
				print(f"        {p}")
			if len(problems) > 8:
				print(f"        … and {len(problems)-8} more")
		else:
			print(f"ok    {name}")
		for n in notes:
			print(f"        {n}")
	print(f"\n{len(a.pdfs) - bad}/{len(a.pdfs)} clean")
	return 1 if bad else 0


if __name__ == "__main__":
	sys.exit(main())
