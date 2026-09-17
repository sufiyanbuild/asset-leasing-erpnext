"""P7 - every report runs, requires its company, and shows live data."""

import importlib

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from asset_leasing.tests.base import LeasingTestCase
from asset_leasing.tests.fixtures import approved_agreement, dispatch, return_doc

REPORTS = {
	"Fleet Utilisation": {"from_date": add_days(nowdate(), -30), "to_date": nowdate()},
	"Asset Rental History": {},
	"Equipment On Hire": {},
	"Overdue Returns": {},
	"Asset Availability": {"from_date": nowdate(), "to_date": add_days(nowdate(), 30)},
	"Rental Revenue by Asset": {},
	"Damage Recovery": {},
	"Agreement Expiry and Renewal": {"days": 60},
	"Rental Receivables": {"as_on": nowdate()},
	"Deposit Register": {},
}


def run(name, filters):
	module = importlib.import_module(
		f"asset_leasing.asset_leasing.report.{frappe.scrub(name)}.{frappe.scrub(name)}"
	)
	return module.execute(frappe._dict(filters))


class TestReports(LeasingTestCase):
	def test_every_report_runs(self):
		agreement = approved_agreement(self.customer, self.asset, security_deposit_amount=1000)
		dispatch(agreement, hours_ago=24 * 5)
		for name, filters in REPORTS.items():
			result = run(name, {"company": self.company, **filters})
			self.assertTrue(result[0], f"{name} has columns")
			self.assertIsInstance(result[1], list, name)

	def test_reports_require_a_company(self):
		for name, filters in REPORTS.items():
			with self.assertRaises(frappe.ValidationError, msg=name):
				run(name, filters)

	def test_live_position_and_history(self):
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement, hours_ago=24 * 3)
		on_hire = run("Equipment On Hire", {"company": self.company})[1]
		self.assertIn(self.asset, [r["asset"] for r in on_hire])
		utilisation = run("Fleet Utilisation", {"company": self.company, "from_date": add_days(nowdate(), -9),
												"to_date": nowdate()})
		row = next(r for r in utilisation[1] if r["asset"] == self.asset)
		self.assertAlmostEqual(row["days_on_hire"], 3, places=0)
		return_doc(agreement)
		history = run("Asset Rental History", {"company": self.company, "asset": self.asset})[1]
		self.assertEqual(history[0]["agreement"], agreement.name)
		self.assertEqual(history[0]["line_status"], "Returned")

	def test_report_records_are_installed(self):
		for name in REPORTS:
			report = frappe.get_doc("Report", name)
			self.assertEqual((report.module, report.is_standard, report.report_type),
							 ("Asset Leasing", "Yes", "Script Report"))
