"""P2 - Rental Agreement integration tests.

These build a real Company, Asset Category, fixed-asset Item and submitted Asset,
because double-booking cannot be proven without two real submitted agreements.
The test runner rolls all of it back.
"""

import frappe
from frappe.tests import IntegrationTestCase

from asset_leasing.rental import asset_status as st
from asset_leasing.tests.fixtures import (
	CONFIRMED,
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

	# ------------------------------------------------------------- pricing
	def test_short_term_estimate_under_confirmed_policy(self):
		"""The agreed period is priced; the billed rent is set only at return."""
		with self.change_settings("Asset Leasing Settings", CONFIRMED):
			doc = make_agreement(self.customer, self.asset, "2027-08-01", "2027-08-10")
		self.assertEqual(doc.items[0].monthly_rate, 45000)
		self.assertEqual(doc.items[0].derived_daily_rate, 1451.61)
		self.assertEqual(doc.estimated_rental_value, 14516.13)
		self.assertFalse(doc.items[0].line_amount, "rent billed is set at return, not at booking")
		self.assertFalse(doc.items[0].billable_days)

	def test_no_estimate_while_policy_unconfirmed(self):
		with self.change_settings("Asset Leasing Settings", {"pricing_policy_confirmed": 0}):
			doc = make_agreement(self.customer, self.asset, "2027-08-01", "2027-08-31")
		self.assertFalse(doc.estimated_rental_value)
		self.assertFalse(doc.items[0].derived_daily_rate)

	def test_open_ended_has_no_estimate(self):
		with self.change_settings("Asset Leasing Settings", CONFIRMED):
			doc = make_agreement(self.customer, self.asset, "2027-09-01", open_ended=True)
		self.assertFalse(doc.estimated_rental_value)

	def test_zero_rate_refused_at_approval(self):
		"""VAL-17/VAL-28: a draft may lack a price; an approved hire may not."""
		unpriced = make_item(f"{PREFIX} Unpriced Hire", is_fixed_asset=0, is_rental_item=1)
		doc = make_agreement(self.customer, self.asset, "2027-10-01", "2027-10-31",
							 items=[{"asset": self.asset, "rental_item": unpriced}])
		self.assertFalse(doc.items[0].monthly_rate)
		with self.assertRaisesRegex(frappe.ValidationError, "no monthly rate"):
			doc.submit()

	def test_free_of_charge_line_may_have_no_rate(self):
		doc = make_agreement(self.customer, self.asset, "2027-11-01", "2027-11-30")
		doc.items[0].is_free_of_charge = 1
		doc.items[0].monthly_rate = 0
		doc.save(ignore_permissions=True)
		doc.submit()
		self.assertEqual(doc.status, "Approved")

	# ---------------------------------------------------------- long term
	def test_long_term_must_have_a_fixed_term(self):
		with self.assertRaisesRegex(frappe.ValidationError, "fixed term"):
			make_agreement(self.customer, self.asset, "2027-01-01", open_ended=True,
						   agreement_type="Long Term Contract")

	def test_long_term_must_end_on_a_billing_boundary(self):
		with self.assertRaisesRegex(frappe.ValidationError, "part-way"):
			make_agreement(self.customer, self.asset, "2027-01-15", "2027-04-20",
						   agreement_type="Long Term Contract")

	def test_long_term_value_is_whole_months(self):
		doc = make_agreement(self.customer, self.asset, "2027-01-15", "2027-07-14",
							 agreement_type="Long Term Contract")
		self.assertEqual(doc.estimated_rental_value, 45000 * 6)

	# ----------------------------------------------------- holder display (15.1)
	def test_cancelling_a_later_booking_keeps_the_earlier_hold(self):
		november = make_agreement(self.customer, self.asset, "2027-11-01", "2027-11-30", submit=True)
		december = make_agreement(self.other_customer, self.asset, "2027-12-01", "2027-12-31", submit=True)
		asset = frappe.db.get_value("Asset", self.asset, ["al_current_agreement", "al_rental_status"], as_dict=True)
		self.assertEqual(asset.al_current_agreement, november.name, "the earliest booking holds the machine")
		december.cancel()
		asset = frappe.db.get_value("Asset", self.asset, ["al_current_agreement", "al_rental_status"], as_dict=True)
		self.assertEqual(asset.al_current_agreement, november.name)
		self.assertEqual(asset.al_rental_status, st.RESERVED)
		november.cancel()
		self.assertEqual(frappe.db.get_value("Asset", self.asset, "al_rental_status"), st.AVAILABLE)

	# ------------------------------------------------------- other guards
	def test_retired_machine_refused(self):
		frappe.db.set_value("Asset", self.asset, "al_rental_status", st.RETIRED)
		with self.assertRaisesRegex(frappe.ValidationError, "retired"):
			make_agreement(self.customer, self.asset, "2028-01-01", "2028-01-31")

	def test_credit_limit_exceeded_is_refused(self):
		customer = make_customer(f"{PREFIX} Over Limit")
		doc = frappe.get_doc("Customer", customer)
		doc.append("credit_limits", {"company": self.company, "credit_limit": 1000})
		doc.save(ignore_permissions=True)
		# Exposure within the limit: saving is fine, approval adds the estimate and is refused.
		with self.change_settings("Asset Leasing Settings", CONFIRMED):
			agreement = make_agreement(customer, self.asset, "2028-02-01", "2028-02-10")
			with self.assertRaisesRegex(frappe.ValidationError, "credit limit"):
				agreement.submit()
			with self.change_settings("Asset Leasing Settings", {"block_dispatch_if_credit_exceeded": 0}):
				agreement.reload()
				agreement.submit()
