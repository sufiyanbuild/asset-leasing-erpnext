"""P8 - daily jobs (T-07) and the notifications they raise."""

import frappe
from frappe.utils import add_days, nowdate

from asset_leasing import tasks
from asset_leasing.rental import asset_status as st
from asset_leasing.tests.base import LeasingTestCase
from asset_leasing.tests.fixtures import approved_agreement, dispatch, make_user, return_doc

MANAGER = "al-sched-manager@example.com"


class TestScheduledJobs(LeasingTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(MANAGER, ["Leasing Manager"])

	def overdue_agreement(self):
		agreement = approved_agreement(self.customer, self.asset, days_ago=20, length=10)
		dispatch(agreement, hours_ago=24 * 18)
		return agreement

	def test_overdue_hire_is_flagged_once(self):
		"""T-07."""
		agreement = self.overdue_agreement()
		self.assertIn(agreement.name, tasks.flag_overdue_returns())
		agreement.reload()
		self.assertTrue(agreement.is_overdue)
		self.assertEqual(str(agreement.overdue_since), nowdate())
		self.assertTrue(frappe.db.exists("Notification Log", {"for_user": MANAGER, "document_name": agreement.name}))
		comments = frappe.db.count("Comment", {"reference_name": agreement.name, "content": ["like", "Overdue:%"]})
		self.assertEqual(comments, 1)

		self.assertNotIn(agreement.name, tasks.flag_overdue_returns(), "raised on first detection only")
		self.assertEqual(frappe.db.count("Comment", {"reference_name": agreement.name, "content": ["like", "Overdue:%"]}), 1)

		from asset_leasing.asset_leasing.report.overdue_returns.overdue_returns import execute
		_columns, rows, *_ = execute({"company": self.company})
		row = next(r for r in rows if r["agreement"] == agreement.name)
		self.assertGreater(row["days_overdue"], 0)
		self.assertIsNotNone(row["rent_to_date"])

		return_doc(agreement)
		agreement.reload()
		self.assertFalse(agreement.is_overdue, "closing the hire clears the flag")

	def test_grace_days_are_respected(self):
		agreement = approved_agreement(self.customer, self.asset, days_ago=5, length=5)
		dispatch(agreement, hours_ago=24)
		with self.change_settings("Asset Leasing Settings", {"overdue_grace_days": 3}):
			self.assertNotIn(agreement.name, tasks.flag_overdue_returns())
		with self.change_settings("Asset Leasing Settings", {"overdue_grace_days": 0}):
			self.assertIn(agreement.name, tasks.flag_overdue_returns())

	def test_open_ended_hire_is_never_overdue(self):
		agreement = approved_agreement(self.customer, self.asset, days_ago=40, open_ended=True)
		dispatch(agreement, hours_ago=24 * 30)
		self.assertNotIn(agreement.name, tasks.flag_overdue_returns())

	def test_compliance_scan_flags_expiry(self):
		frappe.db.set_value("Asset", self.asset, "al_fitness_expiry", add_days(nowdate(), 10))
		self.assertIn(self.asset, tasks.scan_compliance_expiry())
		self.assertEqual(frappe.db.get_value("Asset", self.asset, "al_compliance_status"), "Expiring Soon")
		frappe.db.set_value("Asset", self.asset, "al_fitness_expiry", add_days(nowdate(), -1))
		tasks.scan_compliance_expiry()
		self.assertEqual(frappe.db.get_value("Asset", self.asset, "al_compliance_status"), "Expired")

	def test_reconcile_reports_without_correcting(self):
		from unittest.mock import patch

		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement)
		frappe.db.set_value("Asset", self.asset, "al_rental_status", st.AVAILABLE)
		# Error Log rows outlive the test transaction, so the log call is observed, not made.
		with patch("frappe.log_error") as logged:
			problems = tasks.reconcile_asset_status()
		self.assertTrue(any(self.asset in p for p in problems))
		self.assertIn(self.asset, logged.call_args.kwargs["message"])
		self.assertEqual(self.status(), st.AVAILABLE, "the sweep reports; it never corrects")
		frappe.db.set_value("Asset", self.asset, "al_rental_status", st.ON_HIRE)
		with patch("frappe.log_error"):
			self.assertFalse(any(self.asset in p for p in tasks.reconcile_asset_status()))

	def test_utilisation_cache_counts_hire_in_progress(self):
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement, hours_ago=72)
		frappe.db.set_value("Asset", self.asset, "al_total_hire_days", 0)
		tasks.refresh_utilisation_cache()
		self.assertAlmostEqual(frappe.db.get_value("Asset", self.asset, "al_total_hire_days"), 3, places=1)

	def test_jobs_are_scheduled(self):
		daily = frappe.get_hooks("scheduler_events")["daily"]
		for job in ("flag_overdue_returns", "scan_compliance_expiry", "refresh_utilisation_cache",
					"reconcile_asset_status"):
			self.assertIn(f"asset_leasing.tasks.{job}", daily)
