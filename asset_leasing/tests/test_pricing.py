"""Pro-rata pricing (Q-14 to Q-18) under the client's confirmed policy.

T-06: the client's own worked example is asserted verbatim. The other cases are
the realistic situations the policy was chosen to settle: calendar months of
different lengths, part days, a hire crossing a month end, and a hire longer
than a month. The alternative policy options are exercised too, because a
changed decision must be a settings change and nothing more.
"""

import frappe
from frappe.tests import IntegrationTestCase

from asset_leasing.rental import pricing
from asset_leasing.setup.install import record_confirmed_policy
from asset_leasing.tests.fixtures import CONFIRMED

SETTINGS = "Asset Leasing Settings"


def price(start, end, rate=45000, downtime=0, adjustment=0):
	return pricing.price_hire(rate, start, end, downtime, adjustment)


class TestConfirmedPolicy(IntegrationTestCase):
	def test_client_worked_example_verbatim(self):
		"""4, 5, 10, 20, 30 days -> 6,000 / 7,500 / 15,000 / 30,000 / 45,000 (a 30-day month)."""
		with self.change_settings(SETTINGS, CONFIRMED):
			for days, amount in ((4, 6000), (5, 7500), (10, 15000), (20, 30000), (30, 45000)):
				end = frappe.utils.add_to_date("2026-09-01 09:00:00", days=days)
				result = price("2026-09-01 09:00:00", end)
				self.assertEqual(result.billable_days, days)
				self.assertEqual(result.amount, amount, f"{days} days")
				self.assertEqual(result.daily_rate, 1500)

	def test_actual_days_divisor(self):
		"""Q-14: the same ten days cost more in February than in January."""
		with self.change_settings(SETTINGS, CONFIRMED):
			january = price("2027-01-05 09:00:00", "2027-01-15 09:00:00")
			february = price("2027-02-05 09:00:00", "2027-02-15 09:00:00")
			self.assertEqual((january.divisor, january.amount), (31, 14516.13))
			self.assertEqual((february.divisor, february.amount), (28, 16071.43))

	def test_full_month_always_bills_the_monthly_rate(self):
		with self.change_settings(SETTINGS, CONFIRMED):
			self.assertEqual(price("2027-01-01", "2027-02-01").amount, 45000)
			self.assertEqual(price("2027-02-01", "2027-03-01").amount, 45000)
			self.assertEqual(price("2026-04-01", "2026-05-01").amount, 45000)
			self.assertEqual(price("2028-02-01", "2028-03-01").divisor, 29)  # leap year

	def test_part_day_rounds_up(self):
		"""Q-16: any extra hours count as a full additional day."""
		with self.change_settings(SETTINGS, CONFIRMED):
			self.assertEqual(price("2026-09-07 09:00:00", "2026-09-09 14:00:00").billable_days, 3)
			self.assertEqual(price("2026-09-07 09:00:00", "2026-09-09 09:00:00").billable_days, 2)
			self.assertEqual(price("2026-09-07 09:00:00", "2026-09-09 09:00:01").billable_days, 3)
			self.assertEqual(price("2026-09-07 09:00:00", "2026-09-07 17:00:00").amount, 1500)

	def test_no_minimum_period(self):
		"""Q-15: a one-hour hire is one day, not a minimum block."""
		with self.change_settings(SETTINGS, CONFIRMED):
			result = price("2026-09-07 09:00:00", "2026-09-07 10:00:00")
			self.assertEqual((result.billable_days, result.amount), (1, 1500))

	def test_month_crossing_uses_one_divisor(self):
		"""Q-17: 25 Jan 09:00 to 10 Feb 17:00 is 17 days, all at January's rate."""
		with self.change_settings(SETTINGS, CONFIRMED):
			result = price("2027-01-25 09:00:00", "2027-02-10 17:00:00")
			self.assertEqual(result.billable_days, 17)
			self.assertEqual(result.divisor, 31)
			self.assertEqual(result.amount, 24677.42)
			self.assertEqual(len(result.segments), 1)
			starting_in_feb = price("2027-02-25 09:00:00", "2027-03-10 09:00:00")
			self.assertEqual((starting_in_feb.divisor, starting_in_feb.amount), (28, 20892.86))

	def test_no_cap_at_the_monthly_rate(self):
		"""Q-18: the prorated amount may exceed the monthly rate."""
		with self.change_settings(SETTINGS, CONFIRMED):
			self.assertEqual(price("2026-09-01 08:00:00", "2026-10-02 08:00:00").amount, 46500)
			self.assertEqual(price("2026-09-01 08:00:00", "2026-10-16 08:00:00").amount, 67500)

	def test_downtime_and_adjustment_are_credited_before_rounding(self):
		with self.change_settings(SETTINGS, CONFIRMED):
			self.assertEqual(price("2026-09-01 09:00:00", "2026-09-11 09:00:00", downtime=2).billable_days, 8)
			self.assertEqual(price("2026-09-01 09:00:00", "2026-09-11 09:00:00", downtime=1.5).billable_days, 9)
			self.assertEqual(price("2026-09-01 09:00:00", "2026-09-11 09:00:00", adjustment=1).amount, 13500)

	def test_estimate_counts_calendar_days_inclusive(self):
		with self.change_settings(SETTINGS, CONFIRMED):
			self.assertEqual(pricing.estimate_period_amount(45000, "2026-09-01", "2026-09-30").amount, 45000)
			self.assertEqual(pricing.estimate_period_amount(45000, "2026-10-01", "2026-10-10").amount, 14516.13)

	def test_overdue_days_and_surcharge(self):
		with self.change_settings(SETTINGS, {**CONFIRMED, "overdue_grace_days": 1, "overdue_surcharge_percent": 0}):
			self.assertEqual(pricing.overdue_days("2026-09-10", "2026-09-11 23:00:00"), 0)
			self.assertEqual(pricing.overdue_days("2026-09-10", "2026-09-12 06:00:00"), 1)
			self.assertEqual(pricing.overdue_surcharge(1500, 3), 0)
		with self.change_settings(SETTINGS, {**CONFIRMED, "overdue_surcharge_percent": 10}):
			self.assertEqual(pricing.overdue_surcharge(1500, 3), 450)


class TestOtherPolicyOptions(IntegrationTestCase):
	def test_fixed_thirty(self):
		with self.change_settings(SETTINGS, {**CONFIRMED, "proration_divisor_policy": "Fixed 30 Days"}):
			self.assertEqual(price("2027-01-01", "2027-02-01").amount, 46500)
			self.assertEqual(price("2027-02-01", "2027-03-01").amount, 42000)

	def test_round_down_and_fractional(self):
		with self.change_settings(SETTINGS, {**CONFIRMED, "part_day_policy": "Round Down"}):
			self.assertEqual(price("2026-09-07 09:00:00", "2026-09-09 14:00:00").billable_days, 2)
		with self.change_settings(SETTINGS, {**CONFIRMED, "part_day_policy": "Fractional"}):
			self.assertAlmostEqual(price("2026-09-07 09:00:00", "2026-09-09 15:00:00").billable_days, 2.25)

	def test_minimum_period(self):
		with self.change_settings(SETTINGS, {**CONFIRMED, "has_minimum_rental_period": "Yes", "minimum_billable_days": 3}):
			self.assertEqual(price("2026-09-07 09:00:00", "2026-09-08 09:00:00").billable_days, 3)

	def test_split_at_month_end(self):
		with self.change_settings(SETTINGS, {**CONFIRMED, "month_boundary_policy": "Split At Month End"}):
			result = price("2027-01-25 00:00:00", "2027-02-11 00:00:00")
			self.assertEqual([s["days"] for s in result.segments], [7, 10])
			self.assertEqual(result.amount, 26232.72)

	def test_cap(self):
		with self.change_settings(SETTINGS, {**CONFIRMED, "proration_divisor_policy": "Fixed 30 Days",
											  "cap_at_monthly_rate": "Yes"}):
			self.assertEqual(price("2027-01-01", "2027-02-01").amount, 45000)
			self.assertEqual(price("2026-09-01", "2026-10-06").amount, 52500)


class TestPricingGate(IntegrationTestCase):
	def test_unconfirmed_policy_refuses(self):
		with self.change_settings(SETTINGS, {"pricing_policy_confirmed": 0}):
			self.assertFalse(pricing.policy_ready())
			with self.assertRaises(pricing.PricingPolicyNotConfigured):
				pricing.derive_daily_rate(45000, "2026-09-01")
			with self.assertRaises(pricing.PricingPolicyNotConfigured):
				pricing.compute_billable_days("2026-09-01 09:00:00", "2026-09-05 17:00:00")
			with self.assertRaises(pricing.PricingPolicyNotConfigured):
				pricing.compute_line_amount(45000, "2026-09-01 09:00:00", "2026-09-05 17:00:00")

	def test_settings_refuse_a_half_answered_policy(self):
		settings = frappe.get_doc(SETTINGS)
		settings.pricing_policy_confirmed = 1
		settings.part_day_policy = ""
		with self.assertRaises(frappe.ValidationError):
			settings.save(ignore_permissions=True)

	def test_install_records_the_confirmed_policy_only_when_empty(self):
		blank = frappe.get_doc({"doctype": SETTINGS})
		for field in pricing.UNRESOLVED_POLICY:
			blank.set(field, "")
		self.assertTrue(record_confirmed_policy(blank))
		for field, value in pricing.CONFIRMED_POLICY.items():
			self.assertEqual(blank.get(field), value)
		self.assertTrue(blank.pricing_policy_confirmed)

		decided = frappe.get_doc({"doctype": SETTINGS, "proration_divisor_policy": "Fixed 30 Days"})
		self.assertFalse(record_confirmed_policy(decided))
		self.assertEqual(decided.proration_divisor_policy, "Fixed 30 Days")

	def test_confirmed_policy_matches_the_client_answers(self):
		self.assertEqual(pricing.CONFIRMED_POLICY["proration_divisor_policy"], "Actual Days in Month")
		self.assertEqual(pricing.CONFIRMED_POLICY["has_minimum_rental_period"], "No")
		self.assertEqual(pricing.CONFIRMED_POLICY["part_day_policy"], "Round Up")
		self.assertEqual(pricing.CONFIRMED_POLICY["month_boundary_policy"], "Single Divisor For Whole Hire")
		self.assertEqual(pricing.CONFIRMED_POLICY["cap_at_monthly_rate"], "No")


class TestPolicyFreeArithmetic(IntegrationTestCase):
	def test_elapsed_days(self):
		self.assertAlmostEqual(
			pricing.elapsed_days("2026-09-01 09:00:00", "2026-09-05 17:00:00"), 4.333333, places=5
		)
		self.assertAlmostEqual(pricing.elapsed_days("2026-09-01", "2026-09-11"), 10.0, places=5)

	def test_elapsed_rejects_reversed_dates(self):
		with self.assertRaises(frappe.ValidationError):
			pricing.elapsed_days("2026-09-05 17:00:00", "2026-09-01 09:00:00")

	def test_only_one_rental_price_list(self):
		lists = frappe.get_all("Price List", filters={"name": ["like", "Rental%"]}, pluck="name")
		self.assertEqual(sorted(lists), ["Rental - Monthly"], "no daily or weekly price lists may exist")
