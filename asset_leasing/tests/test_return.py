"""P4 - Rental Return and rental billing (T-03, T-04, T-14)."""

import frappe
from frappe.utils import add_days, add_to_date, flt, get_datetime, now_datetime, nowdate

from asset_leasing.rental import asset_status as st
from asset_leasing.rental import pricing
from asset_leasing.tests.base import LeasingTestCase
from asset_leasing.tests.fixtures import approved_agreement, dispatch, make_agreement, return_doc


class TestReturn(LeasingTestCase):
	def test_return_bills_the_hire_and_frees_the_machine(self):
		"""T-03 under the confirmed pro-rata policy."""
		agreement = approved_agreement(self.customer, self.asset, days_ago=12, length=30)
		sent = dispatch(agreement, hours_ago=24 * 10 + 5)  # 10 days 5 hours ago
		ret = return_doc(agreement)
		agreement.reload()

		expected = pricing.price_hire(45000, sent.dispatch_datetime, ret.return_datetime)
		self.assertEqual(expected.billable_days, 11, "10 days 5 hours rounds up to 11")
		self.assertEqual(ret.items[0].billable_days, 11)
		self.assertEqual(ret.computed_rental_amount, expected.amount)
		self.assertEqual(ret.rental_billing_status, "Invoiced")

		invoice = frappe.get_doc("Sales Invoice", {"al_rental_return": ret.name, "al_invoice_purpose": "Rental"})
		self.assertEqual(invoice.docstatus, 0, "rental invoices are drafts for Finance")
		self.assertEqual(invoice.al_rental_agreement, agreement.name)
		self.assertEqual(len(invoice.items), 1)
		line = invoice.items[0]
		self.assertEqual(line.al_asset, self.asset)
		self.assertFalse(line.asset, "the core asset field would mean disposal")
		self.assertEqual(line.item_code, agreement.items[0].rental_item)
		self.assertEqual(flt(line.amount), expected.amount)
		self.assertEqual(line.al_billable_days, 11)
		self.assertEqual(str(invoice.from_date), str(get_datetime(sent.dispatch_datetime).date()))

		asset = frappe.get_doc("Asset", self.asset)
		self.assertEqual(asset.al_rental_status, st.AVAILABLE)
		self.assertEqual(asset.location, self.yard)
		self.assertIsNone(asset.al_current_agreement)
		self.assertAlmostEqual(asset.al_total_hire_days, ret.items[0].elapsed_days, places=2)
		self.assertEqual(asset.al_last_meter_reading, 150)
		self.assertEqual(agreement.items[0].line_status, "Returned")
		self.assertEqual(agreement.items[0].line_amount, expected.amount)
		self.assertEqual(agreement.status, "Closed")
		self.assertEqual(str(agreement.actual_end_date), str(get_datetime(ret.return_datetime).date()))
		self.assertTrue(ret.is_final_return)

	def test_return_before_dispatch_is_refused(self):
		"""T-04 - the exact defect in the prototype's only contract."""
		agreement = approved_agreement(self.customer, self.asset, days_ago=1)
		sent = dispatch(agreement, hours_ago=2)
		moment = add_to_date(get_datetime(sent.dispatch_datetime), seconds=-90)
		with self.assertRaises(frappe.ValidationError) as ctx:
			return_doc(agreement, return_datetime=moment)
		message = str(ctx.exception)
		self.assertIn(self.asset, message)
		self.assertIn("must be after the dispatch", message)
		self.assertFalse(frappe.db.exists("Rental Return", {"rental_agreement": agreement.name}))

	def test_machine_not_on_hire_cannot_be_returned(self):
		"""VAL-09."""
		agreement = approved_agreement(self.customer, self.asset)
		with self.assertRaisesRegex(frappe.ValidationError, "no equipment on hire|not on hire"):
			return_doc(agreement, items=[{"asset": self.asset, "condition_in": "Good", "post_return_status": "Available"}])

	def test_meter_below_dispatch_refused(self):
		"""VAL-18."""
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement)
		agreement.reload()
		with self.assertRaisesRegex(frappe.ValidationError, "below the reading at dispatch"):
			return_doc(agreement, items=[{"asset": self.asset, "agreement_item": agreement.items[0].name,
										  "condition_in": "Good", "post_return_status": "Available",
										  "meter_reading_in": 90}])

	def test_adjustment_needs_a_reason_and_cannot_exceed_the_hire(self):
		"""VAL-20."""
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement, hours_ago=30)
		with self.assertRaisesRegex(frappe.ValidationError, "reason"):
			return_doc(agreement, submit=False, adjustment_days=1)
		with self.assertRaisesRegex(frappe.ValidationError, "exceed"):
			return_doc(agreement, submit=False, adjustment_days=3, adjustment_reason="Goodwill")
		ret = return_doc(agreement, adjustment_days=0.5, adjustment_reason="Late start on site")
		self.assertEqual(ret.items[0].billable_days, 1, "30 hours less 12 is 18 hours, rounded up to one day")

	def test_partial_return_keeps_the_agreement_open(self):
		second = self.new_asset("-2")
		agreement = make_agreement(self.customer, self.asset, add_days(nowdate(), -5), add_days(nowdate(), 20),
								   items=[{"asset": self.asset}, {"asset": second}], submit=True)
		dispatch(agreement)
		agreement.reload()
		first_line = next(r for r in agreement.items if r.asset == self.asset)
		ret = return_doc(agreement, items=[{"asset": self.asset, "agreement_item": first_line.name,
											"condition_in": "Good", "post_return_status": "Available"}])
		agreement.reload()
		self.assertFalse(ret.is_final_return)
		self.assertEqual(agreement.status, "Partially Returned")
		self.assertIsNone(agreement.actual_end_date)
		self.assertEqual(self.status(second), st.ON_HIRE)

	def test_returned_machine_is_reserved_for_its_next_booking(self):
		agreement = approved_agreement(self.customer, self.asset, days_ago=3, length=5)
		later = make_agreement(self.other_customer, self.asset, add_days(nowdate(), 10), add_days(nowdate(), 20), submit=True)
		dispatch(agreement)
		return_doc(agreement)
		asset = frappe.db.get_value("Asset", self.asset, ["al_rental_status", "al_current_agreement"], as_dict=True)
		self.assertEqual(asset.al_rental_status, st.RESERVED)
		self.assertEqual(asset.al_current_agreement, later.name)

	def test_cancel_return_restores_the_hire(self):
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement)
		ret = return_doc(agreement)
		self.assertTrue(frappe.db.exists("Sales Invoice", {"al_rental_return": ret.name}))
		frappe.get_doc("Rental Return", ret.name).cancel()
		agreement.reload()
		asset = frappe.get_doc("Asset", self.asset)
		self.assertEqual(asset.al_rental_status, st.ON_HIRE)
		self.assertEqual(asset.location, self.site)
		self.assertEqual(asset.al_current_agreement, agreement.name)
		self.assertEqual(asset.al_last_meter_reading, 100)
		self.assertEqual(agreement.status, "Active")
		self.assertEqual(agreement.items[0].line_status, "On Hire")
		self.assertFalse(agreement.items[0].line_amount)
		self.assertFalse(frappe.db.exists("Sales Invoice", {"al_rental_return": ret.name}),
						 "the draft invoice goes with the return")

	def test_cancel_refused_once_invoice_is_submitted(self):
		"""VAL-24 / T-14."""
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement)
		ret = return_doc(agreement)
		invoice = frappe.get_doc("Sales Invoice", {"al_rental_return": ret.name})
		invoice.submit()
		with self.assertRaisesRegex(frappe.ValidationError, "Cancel it first"):
			frappe.get_doc("Rental Return", ret.name).cancel()
		agreement.reload()
		self.assertEqual(agreement.total_billed_amount, invoice.grand_total)
		self.assertEqual(frappe.db.get_value("Asset", self.asset, "al_lifetime_rental_revenue"), invoice.base_net_total)

	def test_no_rent_while_policy_unconfirmed(self):
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement)
		with self.change_settings("Asset Leasing Settings", {"pricing_policy_confirmed": 0}):
			ret = return_doc(agreement)
		self.assertEqual(ret.rental_billing_status, "Awaiting Pricing Policy")
		self.assertFalse(ret.items[0].billable_days)
		self.assertFalse(frappe.db.exists("Sales Invoice", {"al_rental_return": ret.name}))
		self.assertEqual(self.status(), st.AVAILABLE, "the machine still comes back")

	def test_demobilisation_invoice_on_final_return(self):
		agreement = approved_agreement(self.customer, self.asset, demobilisation_charge=4000)
		dispatch(agreement)
		ret = return_doc(agreement)
		invoice = frappe.db.get_value("Sales Invoice", {"al_rental_return": ret.name, "al_invoice_purpose": "Transport"},
									  ["grand_total", "docstatus"], as_dict=True)
		self.assertEqual((invoice.grand_total, invoice.docstatus), (4000, 0))

	def test_overdue_surcharge_is_a_separate_line(self):
		agreement = approved_agreement(self.customer, self.asset, days_ago=10, length=3)
		dispatch(agreement, hours_ago=24 * 9)
		with self.change_settings("Asset Leasing Settings", {"overdue_surcharge_percent": 10, "overdue_grace_days": 1}):
			ret = return_doc(agreement)
		invoice = frappe.get_doc("Sales Invoice", {"al_rental_return": ret.name, "al_invoice_purpose": "Rental"})
		self.assertEqual(len(invoice.items), 2)
		surcharge = invoice.items[1]
		self.assertIn("Overdue surcharge", surcharge.description)
		late = ret.items[0].overdue_days
		self.assertGreater(late, 0)
		daily = 45000 / pricing.days_in_month(get_datetime(ret.items[0].dispatch_datetime))
		self.assertAlmostEqual(surcharge.amount, flt(daily * late * 0.10, 2), places=2)

	def test_waived_surcharge_needs_a_reason(self):
		agreement = approved_agreement(self.customer, self.asset, days_ago=10, length=3)
		dispatch(agreement, hours_ago=24 * 9)
		with self.assertRaisesRegex(frappe.ValidationError, "waiving"):
			return_doc(agreement, submit=False, waive_overdue_surcharge=1)
