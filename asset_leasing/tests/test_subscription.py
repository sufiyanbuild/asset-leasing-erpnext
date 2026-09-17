"""P6 - long-term contracts through ERPNext Subscription (T-09)."""

import frappe
from frappe.utils import add_days, add_months, flt, getdate, nowdate

from asset_leasing.rental import billing
from asset_leasing.tests.base import LeasingTestCase
from asset_leasing.tests.fixtures import dispatch, make_agreement, return_doc


class TestLongTermContract(LeasingTestCase):
	def contract(self, months_ago=1, term=6, asset=None, **kwargs):
		start = add_days(add_months(nowdate(), -months_ago), -5)
		end = add_days(add_months(start, term), -1)
		return make_agreement(self.customer, asset or self.asset, start, end,
							  agreement_type="Long Term Contract", submit=True, **kwargs)

	def test_submit_creates_a_linked_subscription(self):
		"""T-09 - linked both ways, one plan row per machine, drafts for elapsed periods."""
		agreement = self.contract()
		self.assertTrue(agreement.subscription)
		sub = frappe.get_doc("Subscription", agreement.subscription)
		self.assertEqual(sub.al_rental_agreement, agreement.name)
		self.assertEqual((sub.party, str(sub.start_date), str(sub.end_date)),
						 (self.customer, str(agreement.start_date), str(agreement.expected_end_date)))
		self.assertEqual(sub.generate_invoice_at, "Beginning of the current subscription period")
		self.assertFalse(sub.submit_invoice, "Finance reviews every invoice")
		self.assertEqual([(p.al_asset, p.qty) for p in sub.plans], [(self.asset, 1)])
		plan = frappe.get_doc("Subscription Plan", sub.plans[0].plan)
		self.assertEqual((plan.price_determination, plan.cost, plan.billing_interval), ("Fixed Rate", 45000, "Month"))

		invoices = frappe.get_all("Sales Invoice", filters={"subscription": sub.name},
								  fields=["name", "docstatus", "al_rental_agreement", "al_invoice_purpose",
										  "from_date", "to_date", "grand_total"], order_by="from_date")
		self.assertEqual(len(invoices), 2, "the period that started 1 month 5 days ago and the current one")
		for inv in invoices:
			self.assertEqual((inv.docstatus, inv.al_rental_agreement, inv.al_invoice_purpose), (0, agreement.name, "Rental"))
			self.assertEqual(inv.grand_total, 45000)
			line = frappe.get_doc("Sales Invoice", inv.name).items[0]
			self.assertEqual(line.al_asset, self.asset)
			self.assertFalse(line.asset)
		self.assertEqual(getdate(invoices[0].from_date), getdate(agreement.start_date))

	def test_plans_are_reused_and_mapped_per_machine(self):
		second = self.new_asset("-2")
		agreement = self.contract(items=[{"asset": self.asset}, {"asset": second}])
		sub = frappe.get_doc("Subscription", agreement.subscription)
		self.assertEqual(sorted(p.al_asset for p in sub.plans), sorted([self.asset, second]))
		invoice = frappe.get_doc("Sales Invoice", {"subscription": sub.name})
		self.assertEqual(sorted(i.al_asset for i in invoice.items), sorted([self.asset, second]))
		again = billing.get_or_create_plan(agreement.items[0].rental_item, 45000, agreement.currency)
		self.assertEqual(again, sub.plans[0].plan if sub.plans[0].al_asset == self.asset else sub.plans[1].plan)

	def test_cancel_cancels_the_subscription(self):
		agreement = self.contract()
		name = agreement.subscription
		agreement.cancel()
		self.assertEqual(frappe.db.get_value("Subscription", name, "status"), "Cancelled")
		self.assertFalse(frappe.db.exists("Sales Invoice", {"subscription": name, "docstatus": 0}))

	def test_future_contract_generates_nothing_yet(self):
		start = add_days(nowdate(), 10)
		agreement = make_agreement(self.customer, self.asset, start, add_days(add_months(start, 3), -1),
								   agreement_type="Long Term Contract", submit=True)
		self.assertFalse(frappe.db.exists("Sales Invoice", {"subscription": agreement.subscription}))

	def test_return_on_a_contract_does_not_bill_rent(self):
		agreement = self.contract()
		dispatch(agreement, hours_ago=24)
		ret = return_doc(agreement)
		self.assertEqual(ret.rental_billing_status, "Billed by Subscription")
		self.assertFalse(frappe.db.exists("Sales Invoice", {"al_rental_return": ret.name, "al_invoice_purpose": "Rental"}))

	def test_whole_month_boundaries(self):
		self.assertEqual(billing.assert_whole_month_term("2026-09-01", "2027-02-28"), 6)
		self.assertEqual(billing.assert_whole_month_term("2026-01-15", "2026-03-14"), 2)
		with self.assertRaises(frappe.ValidationError):
			billing.assert_whole_month_term("2026-01-15", "2026-02-14")  # a single period
		with self.assertRaises(frappe.ValidationError):
			billing.assert_whole_month_term("2026-01-15", "2026-03-20")
