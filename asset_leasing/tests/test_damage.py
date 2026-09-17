"""P4 - inspection workflow and damage recovery (T-08)."""

import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import flt, now_datetime

from asset_leasing.rental import asset_status as st
from asset_leasing.tests.base import LeasingTestCase
from asset_leasing.tests.fixtures import approved_agreement, dispatch, make_user, return_doc

YARD = "al-yard@example.com"
TECH = "al-tech@example.com"
MANAGER = "al-manager@example.com"


class TestDamage(LeasingTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(YARD, ["Leasing Yard Supervisor"])
		make_user(TECH, ["Leasing Maintenance Technician"])
		make_user(MANAGER, ["Leasing Manager"])

	def draft_return(self, damages):
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement)
		agreement.reload()
		return agreement, return_doc(
			agreement, submit=False, damages=damages, inspected_by=None,
			items=[{"asset": self.asset, "agreement_item": agreement.items[0].name,
					"condition_in": "Damaged", "post_return_status": "Under Repair", "meter_reading_in": 120}],
		)

	def damage(self, cost=15000, chargeable=1, severity="Moderate"):
		return [{"asset": self.asset, "damage_description": "Bucket teeth broken", "severity": severity,
				 "estimated_cost": cost, "chargeable_to_customer": chargeable}]

	def test_damage_needs_manager_approval(self):
		"""T-08 - recorded by the technician, approved only by a Leasing Manager."""
		agreement, ret = self.draft_return(self.damage())
		with self.set_user(YARD):
			ret = apply_workflow(frappe.get_doc("Rental Return", ret.name), "Send for Inspection")
		self.assertEqual(ret.workflow_state, "Pending Inspection")

		with self.set_user(TECH):
			doc = frappe.get_doc("Rental Return", ret.name)
			with self.assertRaises(frappe.ValidationError):
				apply_workflow(doc, "Pass Inspection")  # condition: inspection must have passed
			ret = apply_workflow(frappe.get_doc("Rental Return", ret.name), "Record Damage")
			self.assertEqual(ret.workflow_state, "Damage Assessed")
			self.assertEqual(ret.docstatus, 0)
			self.assertEqual(ret.inspected_by, TECH)
			with self.assertRaises(frappe.ValidationError):
				apply_workflow(frappe.get_doc("Rental Return", ret.name), "Approve Charges")

		with self.set_user(MANAGER):
			ret = apply_workflow(frappe.get_doc("Rental Return", ret.name), "Approve Charges")
		self.assertEqual((ret.workflow_state, ret.docstatus), ("Inspected", 1))

		repair = frappe.get_doc("Asset Repair", {"al_rental_return": ret.name})
		self.assertEqual((repair.asset, repair.al_customer, repair.al_chargeable_to_customer),
						 (self.asset, self.customer, 1))
		self.assertEqual(repair.docstatus, 0)

		invoice = frappe.get_doc("Sales Invoice", {"al_rental_return": ret.name, "al_invoice_purpose": "Damage Recovery"})
		self.assertEqual(invoice.docstatus, 0)
		self.assertEqual(len(invoice.items), 1)
		self.assertEqual(flt(invoice.items[0].amount), 15000)
		self.assertEqual(invoice.items[0].al_asset, self.asset)
		self.assertFalse(invoice.items[0].asset)
		self.assertEqual(self.status(), st.UNDER_REPAIR)
		self.assertTrue(frappe.db.exists("Notification Log", {"for_user": MANAGER, "document_name": ret.name}),
						"the manager was told the damage needs approval")

	def test_technician_cannot_submit_damage_directly(self):
		agreement, ret = self.draft_return(self.damage())
		with self.set_user(YARD):
			apply_workflow(frappe.get_doc("Rental Return", ret.name), "Send for Inspection")
		with self.set_user(TECH):
			ret = apply_workflow(frappe.get_doc("Rental Return", ret.name), "Record Damage")
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc("Rental Return", ret.name).submit()
		self.assertEqual(frappe.db.get_value("Rental Return", ret.name, "docstatus"), 0)

	def test_completed_repair_returns_the_machine_to_service(self):
		agreement, ret = self.draft_return(self.damage())
		ret.submit()
		repair = frappe.get_doc("Asset Repair", {"al_rental_return": ret.name})
		repair.repair_status = "Completed"
		repair.completion_date = now_datetime()
		repair.save(ignore_permissions=True)
		repair.submit()
		self.assertEqual(self.status(), st.AVAILABLE)

	def test_damage_rows_required_when_damage_found(self):
		"""VAL-19."""
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement)
		with self.assertRaisesRegex(frappe.ValidationError, "at least one damage row"):
			return_doc(agreement, submit=False, inspection_result="Damage Found")

	def test_chargeable_damage_needs_a_cost(self):
		with self.assertRaisesRegex(frappe.ValidationError, "estimated cost above zero"):
			self.draft_return(self.damage(cost=0))

	def test_chargeable_damage_must_go_to_repair(self):
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement)
		agreement.reload()
		with self.assertRaisesRegex(frappe.ValidationError, "must be Under Repair"):
			return_doc(agreement, submit=False, damages=self.damage(),
					   items=[{"asset": self.asset, "agreement_item": agreement.items[0].name,
							   "condition_in": "Fair", "post_return_status": "Available"}])

	def test_wear_and_tear_is_not_charged(self):
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement)
		agreement.reload()
		ret = return_doc(agreement, damages=self.damage(cost=2000, chargeable=0),
						 items=[{"asset": self.asset, "agreement_item": agreement.items[0].name,
								 "condition_in": "Fair", "post_return_status": "Available"}])
		self.assertFalse(frappe.db.exists("Sales Invoice", {"al_rental_return": ret.name,
															"al_invoice_purpose": "Damage Recovery"}))
		self.assertFalse(frappe.db.exists("Asset Repair", {"al_rental_return": ret.name}))
		self.assertEqual(ret.total_damage_estimate, 2000)
		self.assertEqual(ret.total_chargeable_damage, 0)

	def test_cancel_removes_open_repair_and_draft_invoice(self):
		agreement, ret = self.draft_return(self.damage())
		ret.submit()
		frappe.get_doc("Rental Return", ret.name).cancel()
		self.assertFalse(frappe.db.exists("Asset Repair", {"al_rental_return": ret.name}))
		self.assertFalse(frappe.db.exists("Sales Invoice", {"al_rental_return": ret.name}))
		self.assertEqual(self.status(), st.ON_HIRE)
