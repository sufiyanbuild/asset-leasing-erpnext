"""T-P1-02, 03, 07, 08 - server-side business rules.

Handlers are exercised directly against unsaved documents where a full
integration fixture would require a Company and chart of accounts. The code path
under test is identical; only the persistence is skipped.
"""

import frappe
from frappe.tests import IntegrationTestCase

from asset_leasing.events import asset as asset_events
from asset_leasing.events import customer as customer_events
from asset_leasing.events import item as item_events
from asset_leasing.rental import validators
from asset_leasing.tests.fixtures import make_customer, make_item, make_location


class TestAssetValidation(IntegrationTestCase):
	def _new_asset(self, **kwargs):
		doc = frappe.new_doc("Asset")
		doc.update(kwargs)
		return doc

	def test_rentable_requires_charge_item(self):
		"""VAL-P1-01"""
		doc = self._new_asset(al_is_rentable=1)
		with self.assertRaises(frappe.ValidationError) as ctx:
			asset_events.validate(doc)
		self.assertIn("Rental Charge Item", str(ctx.exception))

	def test_rentable_requires_home_location(self):
		"""VAL-P1-01"""
		item = make_item("_AL Rent Charge A", is_rental_item=1)
		doc = self._new_asset(al_is_rentable=1, al_rental_item=item)
		with self.assertRaises(frappe.ValidationError) as ctx:
			asset_events.validate(doc)
		self.assertIn("Home / Yard Location", str(ctx.exception))

	def test_non_rentable_asset_is_untouched(self):
		"""The handler must exit early and impose nothing on ordinary assets."""
		doc = self._new_asset(al_is_rentable=0)
		asset_events.validate(doc)  # must not raise

	def test_fixed_asset_item_rejected_as_charge_item(self):
		"""VAL-P1-02 - the trap that would mark equipment Sold."""
		fixed_item = make_item("_AL Machine A", is_fixed_asset=1)
		location = make_location("_AL Yard A")
		doc = self._new_asset(al_is_rentable=1, al_rental_item=fixed_item, al_base_location=location)
		with self.assertRaises(frappe.ValidationError) as ctx:
			asset_events.validate(doc)
		self.assertIn("Fixed Asset", str(ctx.exception))

	def test_valid_rentable_asset_passes(self):
		item = make_item("_AL Rent Charge B", is_rental_item=1)
		location = make_location("_AL Yard B")
		doc = self._new_asset(al_is_rentable=1, al_rental_item=item, al_base_location=location)
		asset_events.validate(doc)
		self.assertEqual(doc.al_rental_status, "Available")


class TestItemValidation(IntegrationTestCase):
	def test_rental_item_cannot_be_fixed_asset(self):
		"""VAL-P1-06"""
		doc = frappe.new_doc("Item")
		doc.update({"al_is_rental_item": 1, "is_fixed_asset": 1})
		with self.assertRaises(frappe.ValidationError) as ctx:
			item_events.validate(doc)
		self.assertIn("cannot be both", str(ctx.exception))

	def test_ordinary_item_untouched(self):
		doc = frappe.new_doc("Item")
		doc.update({"al_is_rental_item": 0, "is_fixed_asset": 1})
		item_events.validate(doc)  # must not raise


class TestCustomerValidation(IntegrationTestCase):
	def test_block_requires_reason(self):
		"""VAL-P1-08"""
		doc = frappe.new_doc("Customer")
		doc.update({"al_hire_blocked": 1, "al_hire_block_reason": ""})
		with self.assertRaises(frappe.ValidationError) as ctx:
			customer_events.validate(doc)
		self.assertIn("Reason for Block", str(ctx.exception))

	def test_block_with_reason_passes(self):
		doc = frappe.new_doc("Customer")
		doc.update({"al_hire_blocked": 1, "al_hire_block_reason": "Unpaid damage claim"})
		customer_events.validate(doc)

	def test_negative_deposit_rejected(self):
		doc = frappe.new_doc("Customer")
		doc.update({"al_deposit_held": -1})
		with self.assertRaises(frappe.ValidationError):
			customer_events.validate(doc)

	def test_blocked_customer_blocks_hire(self):
		name = make_customer("_AL Blocked Co", blocked=True)
		with self.assertRaises(frappe.ValidationError) as ctx:
			validators.assert_customer_not_blocked(name)
		self.assertIn("blocked for hire", str(ctx.exception).lower())

	def test_unblocked_customer_passes(self):
		name = make_customer("_AL Open Co", blocked=False)
		validators.assert_customer_not_blocked(name)
