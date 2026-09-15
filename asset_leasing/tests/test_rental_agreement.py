"""P2 - Rental Agreement integration tests.

These build a real Company, Asset Category, fixed-asset Item and submitted Asset,
because double-booking cannot be proven without two real submitted agreements.
The test runner rolls all of it back.
"""

import frappe
from frappe.tests import IntegrationTestCase

from asset_leasing.rental import asset_status as st
from asset_leasing.tests.fixtures import (
	PREFIX,
	ensure_company,
	make_agreement,
	make_customer,
	make_item,
	make_location,
	make_rentable_asset,
)


class TestRentalAgreement(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = ensure_company()
		cls.customer = make_customer(f"{PREFIX} Hirer")
		cls.other_customer = make_customer(f"{PREFIX} Other Hirer")
		cls.site = make_location(f"{PREFIX} Site", "Customer Site")

	def setUp(self):
		"""A machine of its own for every test.

		Submitting an agreement writes through db.set_value and add_comment, which
		survive the per-test rollback, so a shared asset would make each test
		depend on the ones that ran before it. One asset per test removes that.
		"""
		super().setUp()
		self.asset = make_rentable_asset(f"EX-{self._testMethodName[-24:]}")

	# ------------------------------------------------------------ happy path
	def test_agreement_saves_and_fetches_rate(self):
		doc = make_agreement(self.customer, self.asset, "2026-03-01", "2026-03-31")
		self.assertEqual(doc.status, "Draft")
		self.assertEqual(doc.items[0].line_status, "Pending Dispatch")
		self.assertEqual(doc.items[0].monthly_rate, 45000)
		self.assertEqual(doc.items[0].expected_days, 31)

	def test_submit_reserves_the_machine(self):
		doc = make_agreement(self.customer, self.asset, "2026-04-01", "2026-04-30", submit=True)
		self.assertEqual(doc.status, "Approved")
		asset = frappe.db.get_value(
			"Asset", self.asset, ["al_rental_status", "al_current_agreement", "al_current_customer"],
			as_dict=True,
		)
		self.assertEqual(asset.al_rental_status, st.RESERVED)
		self.assertEqual(asset.al_current_agreement, doc.name)
		self.assertEqual(asset.al_current_customer, self.customer)

	def test_cancel_releases_the_machine(self):
		doc = make_agreement(self.customer, self.asset, "2026-05-01", "2026-05-31", submit=True)
		doc.cancel()
		asset = frappe.db.get_value(
			"Asset", self.asset, ["al_rental_status", "al_current_agreement"], as_dict=True
		)
		self.assertEqual(asset.al_rental_status, st.AVAILABLE)
		self.assertIsNone(asset.al_current_agreement)

	# --------------------------------------------------------- double booking
	def test_overlapping_agreement_is_refused(self):
		"""The core P2 protection."""
		make_agreement(self.customer, self.asset, "2026-06-01", "2026-06-30", submit=True)
		with self.assertRaises(frappe.ValidationError) as ctx:
			make_agreement(self.other_customer, self.asset, "2026-06-15", "2026-07-15")
		message = str(ctx.exception)
		self.assertIn("already committed", message)
		self.assertIn(self.customer, message)

	def test_non_overlapping_agreement_is_allowed(self):
		make_agreement(self.customer, self.asset, "2026-08-01", "2026-08-31", submit=True)
		later = make_agreement(self.other_customer, self.asset, "2026-09-01", "2026-09-30")
		self.assertEqual(later.status, "Draft")

	def test_open_ended_blocks_later_bookings(self):
		make_agreement(self.customer, self.asset, "2026-10-01", open_ended=True, submit=True)
		with self.assertRaises(frappe.ValidationError):
			make_agreement(self.other_customer, self.asset, "2026-12-01", "2026-12-31")

	def test_draft_agreement_does_not_block(self):
		"""Only submitted agreements hold a claim."""
		make_agreement(self.customer, self.asset, "2027-01-01", "2027-01-31")  # draft
		second = make_agreement(self.other_customer, self.asset, "2027-01-15", "2027-02-15")
		self.assertEqual(second.status, "Draft")

	# ------------------------------------------------------------ validation
	def test_end_before_start_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			make_agreement(self.customer, self.asset, "2026-03-31", "2026-03-01")
		self.assertIn("cannot be before", str(ctx.exception))

	def test_duplicate_machine_on_one_agreement_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			make_agreement(
				self.customer, self.asset, "2027-03-01", "2027-03-31",
				items=[{"asset": self.asset}, {"asset": self.asset}],
			)
		self.assertIn("already appears", str(ctx.exception))

	def test_blocked_customer_is_refused(self):
		blocked = make_customer(f"{PREFIX} Barred", blocked=True)
		with self.assertRaises(frappe.ValidationError) as ctx:
			make_agreement(blocked, self.asset, "2027-04-01", "2027-04-30")
		self.assertIn("blocked for hire", str(ctx.exception).lower())

	def test_wet_hire_requires_an_operator(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			make_agreement(
				self.customer, self.asset, "2027-05-01", "2027-05-31", hire_type="Wet Hire"
			)
		self.assertIn("operator", str(ctx.exception).lower())

	def test_non_rentable_asset_is_refused(self):
		frappe.db.set_value("Asset", self.asset, "al_is_rentable", 0)
		try:
			with self.assertRaises(frappe.ValidationError) as ctx:
				make_agreement(self.customer, self.asset, "2027-06-01", "2027-06-30")
			self.assertIn("Available for Rental", str(ctx.exception))
		finally:
			frappe.db.set_value("Asset", self.asset, "al_is_rentable", 1)

	def test_open_ended_clears_end_date(self):
		doc = make_agreement(self.customer, self.asset, "2027-07-01", "2027-07-31", open_ended=True)
		self.assertIsNone(doc.expected_end_date)
		self.assertEqual(doc.items[0].expected_days, 0)

	# --------------------------------------------------------- pricing gated
	def test_pricing_remains_gated(self):
		"""P2 records the agreed monthly rate but must derive nothing from it."""
		doc = make_agreement(self.customer, self.asset, "2027-08-01", "2027-08-31")
		self.assertEqual(doc.items[0].monthly_rate, 45000)
		self.assertFalse(doc.items[0].line_amount, "line amount must stay blank until Q-14 to Q-18")
		self.assertFalse(doc.items[0].billable_days, "billable days must stay blank")
		self.assertFalse(doc.estimated_rental_value, "estimated value must stay blank")
