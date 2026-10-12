import frappe
from frappe.tests.utils import FrappeTestCase


class TestProbe(FrappeTestCase):
	def test_probe(self):
		out = []
		for dt in ("Quotation Item", "Sales Order Item", "Sales Invoice Item", "Delivery Note Item"):
			meta = frappe.get_meta(dt)
			names = [f.fieldname for f in meta.fields]
			grid = [(f.fieldname, f.columns, f.hidden) for f in meta.fields if f.in_list_view]
			out.append(f"{dt}: grid={grid} idx rate={names.index('rate')} amount={names.index('amount')} actual_qty={names.index('actual_qty') if 'actual_qty' in names else None} val={names.index('custom_valuation_rate')}")
		self.fail("\n" + "\n".join(out))
