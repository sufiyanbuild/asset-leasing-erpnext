"""T-P1-04, T-P1-10 - the core-asset guard.

The most important rule in P1. Sales Invoice Item.asset means "this invoice
disposes of this asset". Setting it on a rental line would mark the customer's
equipment Sold on the books.
"""

import frappe
from frappe.tests import IntegrationTestCase

from asset_leasing.events import sales_invoice as si_events


def _doc(items, purpose="Standard"):
	"""A minimal stand-in for a Sales Invoice.

	The handler reads only items, al_invoice_purpose and the row fields, so this
	exercises the real code path without needing a Company and chart of accounts.
	"""
	rows = []
	for idx, row in enumerate(items, start=1):
		row = frappe._dict(row)
		row.idx = idx
		rows.append(row)
	return frappe._dict({"items": rows, "al_invoice_purpose": purpose})


class TestSalesInvoiceGuard(IntegrationTestCase):
	def test_core_asset_and_al_asset_together_is_refused(self):
		"""VAL-P1-07 - the rule that prevents disposing of rented equipment."""
		doc = _doc([{"al_asset": "ASSET-X", "asset": "ASSET-X"}], purpose="Rental")
		with self.assertRaises(frappe.ValidationError) as ctx:
			si_events.validate(doc)
		message = str(ctx.exception)
		self.assertIn("disposal", message.lower())
		self.assertIn("Row #1", message)

	def test_core_asset_alone_is_allowed(self):
		"""A genuine asset-disposal invoice must still work untouched."""
		doc = _doc([{"asset": "ASSET-X"}], purpose="Standard")
		si_events.validate(doc)  # must not raise

	def test_ordinary_invoice_is_untouched(self):
		"""T-P1-10 - the handler must exit early on unrelated invoices."""
		doc = _doc([{"item_code": "SOME-ITEM", "qty": 1}], purpose="Standard")
		si_events.validate(doc)  # must not raise

	def test_unknown_asset_is_refused(self):
		doc = _doc([{"al_asset": "_AL Does Not Exist"}], purpose="Rental")
		with self.assertRaises(frappe.ValidationError) as ctx:
			si_events.validate(doc)
		self.assertIn("does not exist", str(ctx.exception))

	def test_rental_purpose_requires_equipment(self):
		doc = _doc([{"item_code": "SOME-ITEM", "qty": 1}], purpose="Rental")
		with self.assertRaises(frappe.ValidationError) as ctx:
			si_events.validate(doc)
		self.assertIn("no line identifies any equipment", str(ctx.exception))
