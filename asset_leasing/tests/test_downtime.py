"""P5 - downtime credit (T-10, VAL-04)."""

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from asset_leasing.tests.base import LeasingTestCase
from asset_leasing.tests.fixtures import approved_agreement, dispatch, return_doc


def log(agreement, asset, start, hours, creditable=1, submit=True, reason="Breakdown"):
	doc = frappe.get_doc({
		"doctype": "Rental Downtime Log", "rental_agreement": agreement.name, "asset": asset,
		"from_datetime": start, "to_datetime": add_to_date(start, hours=hours), "reason": reason,
		"is_creditable": creditable, "remarks": "Engine failure on site" if creditable else "",
	}).insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


class TestDowntime(LeasingTestCase):
	def ten_day_hire(self):
		agreement = approved_agreement(self.customer, self.asset, days_ago=12, length=30)
		sent = dispatch(agreement, hours_ago=240)
		return agreement, get_datetime(sent.dispatch_datetime)

	def test_approved_creditable_downtime_reduces_billable_days(self):
		"""T-10 - a ten-day hire with a two-day approved breakdown bills eight days."""
		agreement, out = self.ten_day_hire()
		downtime = log(agreement, self.asset, add_to_date(out, days=2), 48)
		self.assertEqual(downtime.downtime_hours, 48)
		self.assertEqual(downtime.approved_by, "Administrator")
		ret = return_doc(agreement, return_datetime=add_to_date(out, days=10))
		self.assertAlmostEqual(ret.items[0].downtime_days, 2, places=4)
		self.assertEqual(ret.items[0].billable_days, 8)

	def test_unapproved_or_non_creditable_downtime_changes_nothing(self):
		agreement, out = self.ten_day_hire()
		log(agreement, self.asset, add_to_date(out, days=1), 24, submit=False)
		log(agreement, self.asset, add_to_date(out, days=4), 24, creditable=0, reason="Weather")
		ret = return_doc(agreement, return_datetime=add_to_date(out, days=10))
		self.assertEqual(ret.items[0].downtime_days, 0)
		self.assertEqual(ret.items[0].billable_days, 10)

	def test_downtime_before_dispatch_refused(self):
		"""VAL-04."""
		agreement, out = self.ten_day_hire()
		with self.assertRaisesRegex(frappe.ValidationError, "before .* was dispatched"):
			log(agreement, self.asset, add_to_date(out, hours=-5), 10)

	def test_overlapping_approved_downtime_refused(self):
		agreement, out = self.ten_day_hire()
		log(agreement, self.asset, add_to_date(out, days=1), 24)
		with self.assertRaisesRegex(frappe.ValidationError, "overlaps"):
			log(agreement, self.asset, add_to_date(out, days=1, hours=12), 24)

	def test_future_downtime_refused(self):
		agreement, out = self.ten_day_hire()
		with self.assertRaisesRegex(frappe.ValidationError, "future"):
			log(agreement, self.asset, add_to_date(now_datetime(), hours=-1), 5)

	def test_creditable_downtime_needs_remarks(self):
		agreement, out = self.ten_day_hire()
		doc = frappe.get_doc({
			"doctype": "Rental Downtime Log", "rental_agreement": agreement.name, "asset": self.asset,
			"from_datetime": add_to_date(out, days=1), "to_datetime": add_to_date(out, days=2),
			"reason": "Breakdown", "is_creditable": 1,
		})
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_creditable_downtime_after_return_refused(self):
		agreement, out = self.ten_day_hire()
		return_doc(agreement, return_datetime=add_to_date(out, days=10))
		with self.assertRaisesRegex(frappe.ValidationError, "before the return is"):
			log(agreement, self.asset, add_to_date(out, days=2), 24)
		# a non-creditable record for analysis is still allowed
		kept = log(agreement, self.asset, add_to_date(out, days=2), 24, creditable=0, reason="Site Closure")
		self.assertEqual(kept.docstatus, 1)

	def test_machine_never_dispatched_has_no_downtime(self):
		agreement = approved_agreement(self.customer, self.asset)
		with self.assertRaisesRegex(frappe.ValidationError, "has not been dispatched"):
			log(agreement, self.asset, add_to_date(now_datetime(), days=-1), 5)
