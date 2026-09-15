"""T-P1-11 - P1 must not have quietly enabled pricing.

Q-14 to Q-18 remain unanswered. Every gated function must still refuse, and the
five policy fields must still be unset.
"""

import frappe
from frappe.tests import IntegrationTestCase

from asset_leasing.rental import pricing


class TestPricingStillBlocked(IntegrationTestCase):
	def test_policy_fields_remain_unset(self):
		settings = frappe.get_single("Asset Leasing Settings")
		self.assertFalse(settings.pricing_policy_confirmed, "pricing policy must not be confirmed")
		for fieldname in pricing.UNRESOLVED_POLICY:
			self.assertIn(
				settings.get(fieldname), (None, ""),
				f"{fieldname} must remain unset until the client answers",
			)

	def test_gated_functions_refuse(self):
		with self.assertRaises(pricing.PricingPolicyNotConfigured):
			pricing.derive_daily_rate(45000)
		with self.assertRaises(pricing.PricingPolicyNotConfigured):
			pricing.compute_billable_days("2026-09-01 09:00:00", "2026-09-05 17:00:00")
		with self.assertRaises(pricing.PricingPolicyNotConfigured):
			pricing.compute_line_amount(45000, "2026-09-01 09:00:00", "2026-09-05 17:00:00")

	def test_settled_arithmetic_still_works(self):
		"""Elapsed duration needs no policy and must remain available."""
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
