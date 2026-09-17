"""P5 - security deposits on Payment Entry (AL-10, VAL-21)."""

import frappe
from frappe.utils import flt

from asset_leasing.rental import deposits
from asset_leasing.tests.base import LeasingTestCase
from asset_leasing.tests.fixtures import approved_agreement, dispatch, return_doc


class TestDeposits(LeasingTestCase):
	def entry(self, agreement, kind, amount=None, submit=True):
		data = deposits.make_deposit_entry(agreement.name, kind)
		pe = frappe.get_doc(data)
		if amount is not None:
			pe.paid_amount = pe.received_amount = amount
		pe.reference_no = "DEP-TEST"
		pe.reference_date = frappe.utils.nowdate()
		pe.insert(ignore_permissions=True)
		if submit:
			pe.submit()
		return pe

	def test_receipt_and_refund_roll_up(self):
		agreement = approved_agreement(self.customer, self.asset, security_deposit_amount=50000)
		receipt = self.entry(agreement, deposits.RECEIVED)
		self.assertEqual(receipt.paid_amount, 50000)
		self.assertEqual(receipt.paid_from, frappe.db.get_single_value("Asset Leasing Settings", "deposit_liability_account"))
		agreement.reload()
		self.assertTrue(agreement.deposit_received)
		self.assertEqual(agreement.deposit_held, 50000)
		self.assertEqual(frappe.db.get_value("Customer", self.customer, "al_deposit_held"), 50000)

		refund = self.entry(agreement, deposits.REFUND)
		self.assertEqual(refund.paid_amount, 50000)
		agreement.reload()
		self.assertEqual(agreement.deposit_held, 0)
		self.assertEqual(frappe.db.get_value("Customer", self.customer, "al_deposit_held"), 0)

		refund.cancel()
		agreement.reload()
		self.assertEqual(agreement.deposit_held, 50000)

	def test_refund_cannot_exceed_the_deposit(self):
		"""VAL-21."""
		agreement = approved_agreement(self.customer, self.asset, security_deposit_amount=20000)
		self.entry(agreement, deposits.RECEIVED)
		with self.assertRaisesRegex(frappe.ValidationError, "exceeds the refundable deposit"):
			self.entry(agreement, deposits.REFUND, amount=25000)

	def test_refund_is_net_of_unrecovered_damage(self):
		agreement = approved_agreement(self.customer, self.asset, security_deposit_amount=30000)
		self.entry(agreement, deposits.RECEIVED)
		dispatch(agreement)
		agreement.reload()
		return_doc(agreement, damages=[{"asset": self.asset, "damage_description": "Cracked glass",
										"severity": "Minor", "estimated_cost": 12000, "chargeable_to_customer": 1}],
				   items=[{"asset": self.asset, "agreement_item": agreement.items[0].name,
						   "condition_in": "Fair", "post_return_status": "Under Repair"}])
		self.assertEqual(deposits.outstanding_damage(agreement.name), 12000)
		self.assertEqual(deposits.refundable_amount(agreement.name, self.customer, self.company), 18000)
		with self.assertRaisesRegex(frappe.ValidationError, "exceeds"):
			self.entry(agreement, deposits.REFUND, amount=20000)
		self.assertEqual(self.entry(agreement, deposits.REFUND).paid_amount, 18000)

	def test_deposit_must_use_the_liability_account(self):
		agreement = approved_agreement(self.customer, self.asset, security_deposit_amount=10000)
		pe = frappe.get_doc(deposits.make_deposit_entry(agreement.name, deposits.RECEIVED))
		pe.paid_from = frappe.db.get_value("Company", self.company, "default_receivable_account")
		pe.reference_no, pe.reference_date = "X", frappe.utils.nowdate()
		with self.assertRaisesRegex(frappe.ValidationError, "deposit liability account"):
			pe.insert(ignore_permissions=True)

	def test_deposit_party_must_match_the_agreement(self):
		agreement = approved_agreement(self.customer, self.asset, security_deposit_amount=10000)
		pe = frappe.get_doc(deposits.make_deposit_entry(agreement.name, deposits.RECEIVED))
		pe.party = self.other_customer
		pe.reference_no, pe.reference_date = "X", frappe.utils.nowdate()
		with self.assertRaisesRegex(frappe.ValidationError, "deposit party must be"):
			pe.insert(ignore_permissions=True)

	def test_ordinary_payments_are_untouched(self):
		pe = frappe.get_doc({"doctype": "Payment Entry", "al_deposit_type": ""})
		self.assertIsNone(deposits.validate(pe))
