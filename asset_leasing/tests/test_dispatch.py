"""P3 - Rental Dispatch and Asset Movement (T-02, T-11, T-14, T-16)."""

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from asset_leasing.rental import asset_status as st
from asset_leasing.tests.base import LeasingTestCase
from asset_leasing.tests.fixtures import PREFIX, approved_agreement, dispatch, make_agreement, return_doc


class TestDispatch(LeasingTestCase):
	def test_dispatch_puts_machine_on_hire(self):
		"""T-02."""
		agreement = approved_agreement(self.customer, self.asset)
		doc = dispatch(agreement)
		agreement.reload()
		asset = frappe.get_doc("Asset", self.asset)
		self.assertEqual(asset.al_rental_status, st.ON_HIRE)
		self.assertEqual(asset.location, self.site)
		self.assertEqual(asset.al_current_agreement, agreement.name)
		self.assertEqual(asset.al_current_customer, self.customer)
		self.assertEqual(asset.al_last_meter_reading, 100)
		self.assertEqual(agreement.status, "Active")
		self.assertEqual(agreement.items[0].line_status, "On Hire")
		self.assertEqual(str(agreement.items[0].dispatch_datetime), str(doc.dispatch_datetime))
		self.assertEqual(doc.status, "Dispatched")

	def test_one_transfer_movement_for_all_machines(self):
		"""T-16 - one movement, purpose Transfer, a row per machine, back-referenced."""
		second = self.new_asset("-2")
		agreement = make_agreement(self.customer, self.asset, add_days(nowdate(), -5), add_days(nowdate(), 20),
								   items=[{"asset": self.asset}, {"asset": second}], submit=True)
		doc = dispatch(agreement)
		movement = frappe.get_doc("Asset Movement", doc.asset_movement)
		self.assertEqual(movement.purpose, "Transfer")
		self.assertEqual(movement.docstatus, 1)
		self.assertEqual((movement.reference_doctype, movement.reference_name), ("Rental Dispatch", doc.name))
		self.assertEqual(sorted(r.asset for r in movement.assets), sorted([self.asset, second]))
		for row in movement.assets:
			self.assertEqual((row.source_location, row.target_location), (self.yard, self.site))
		self.assertEqual(frappe.db.count("Asset Movement", {"reference_name": doc.name}), 1)

	def test_future_dispatch_refused(self):
		"""VAL-03."""
		agreement = approved_agreement(self.customer, self.asset)
		with self.assertRaisesRegex(frappe.ValidationError, "future"):
			dispatch(agreement, hours_ago=-5)

	def test_dispatch_before_agreement_start_refused(self):
		agreement = make_agreement(self.customer, self.asset, add_days(nowdate(), -1), add_days(nowdate(), 10), submit=True)
		with self.assertRaisesRegex(frappe.ValidationError, "before the agreement start"):
			dispatch(agreement, hours_ago=72)

	def test_draft_agreement_cannot_dispatch(self):
		"""VAL-13."""
		agreement = make_agreement(self.customer, self.asset, add_days(nowdate(), -5), add_days(nowdate(), 5))
		with self.assertRaisesRegex(frappe.ValidationError, "approved agreement"):
			dispatch(agreement, submit=False, items=[{"asset": self.asset, "condition_out": "Good"}])

	def test_machine_not_on_agreement_refused(self):
		"""VAL-12."""
		agreement = approved_agreement(self.customer, self.asset)
		stranger = self.new_asset("-x")
		with self.assertRaisesRegex(frappe.ValidationError, "not waiting for dispatch"):
			dispatch(agreement, items=[{"asset": stranger, "condition_out": "Good"}])

	def test_machine_must_be_at_the_dispatch_yard(self):
		agreement = approved_agreement(self.customer, self.asset)
		elsewhere = frappe.get_doc({"doctype": "Location", "location_name": f"{PREFIX} Other Yard",
									"al_location_type": "Owned Yard"}).insert(ignore_permissions=True)
		with self.assertRaisesRegex(frappe.ValidationError, "Dispatch it from the yard"):
			dispatch(agreement, from_location=elsewhere.name)

	def test_machine_under_repair_refused(self):
		"""VAL-07 / AL-04."""
		agreement = approved_agreement(self.customer, self.asset)
		repair = frappe.get_doc({"doctype": "Asset Repair", "asset": self.asset, "company": self.company,
								 "failure_date": now_datetime(), "repair_status": "Pending",
								 "description": "Hydraulic leak"}).insert(ignore_permissions=True)
		with self.assertRaisesRegex(frappe.ValidationError, repair.name):
			dispatch(agreement)

	def test_expired_insurance_blocks_dispatch(self):
		"""T-11 / VAL-16."""
		agreement = approved_agreement(self.customer, self.asset)
		# checked at the dispatch moment, which the fixture places two days back
		frappe.db.set_value("Asset", self.asset, "insurance_end_date", add_days(nowdate(), -5))
		with self.assertRaisesRegex(frappe.ValidationError, "Insurance expired"):
			dispatch(agreement)
		frappe.db.set_value("Asset", self.asset, {"insurance_end_date": None, "al_permit_expiry": add_days(nowdate(), -3)})
		with self.assertRaisesRegex(frappe.ValidationError, "Permit expired"):
			dispatch(agreement)

	def test_transport_details_required_for_own_vehicle(self):
		agreement = approved_agreement(self.customer, self.asset)
		with self.assertRaises(frappe.ValidationError):
			dispatch(agreement, transport_mode="Own Vehicle")
		doc = dispatch(agreement, transport_mode="Own Vehicle", vehicle_no="MH01AB1234", driver_name="R. Patil")
		self.assertEqual(doc.docstatus, 1)

	def test_mobilisation_invoice_raised_at_first_dispatch(self):
		agreement = approved_agreement(self.customer, self.asset, mobilisation_charge=5000)
		doc = dispatch(agreement)
		invoices = frappe.get_all("Sales Invoice", filters={"al_rental_dispatch": doc.name},
								  fields=["name", "docstatus", "al_invoice_purpose", "grand_total"])
		self.assertEqual(len(invoices), 1)
		self.assertEqual((invoices[0].docstatus, invoices[0].al_invoice_purpose), (0, "Transport"))
		self.assertEqual(invoices[0].grand_total, 5000)

	def test_missing_transport_item_does_not_block_dispatch(self):
		agreement = approved_agreement(self.customer, self.asset, mobilisation_charge=5000)
		with self.change_settings("Asset Leasing Settings", {"transport_charge_item": None}):
			doc = dispatch(agreement)
		self.assertEqual(doc.docstatus, 1)
		self.assertFalse(frappe.db.exists("Sales Invoice", {"al_rental_dispatch": doc.name}))
		self.assertTrue(frappe.db.exists("Comment", {
			"reference_name": agreement.name, "content": ["like", "%Invoice not raised automatically%"]}))

	def test_cancel_restores_everything(self):
		agreement = approved_agreement(self.customer, self.asset, mobilisation_charge=5000)
		doc = dispatch(agreement)
		movement = doc.asset_movement
		doc.cancel()
		agreement.reload()
		self.assertEqual(frappe.db.get_value("Asset Movement", movement, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Asset", self.asset, "location"), self.yard)
		self.assertEqual(self.status(), st.RESERVED)
		self.assertEqual(agreement.items[0].line_status, "Pending Dispatch")
		self.assertIsNone(agreement.items[0].dispatch_datetime)
		self.assertEqual(agreement.status, "Approved")
		self.assertFalse(frappe.db.exists("Sales Invoice", {"al_rental_dispatch": doc.name}))

	def test_cancel_refused_after_return(self):
		"""VAL-23 / T-14."""
		agreement = approved_agreement(self.customer, self.asset)
		doc = dispatch(agreement)
		return_doc(agreement)
		with self.assertRaisesRegex(frappe.ValidationError, "already been returned"):
			frappe.get_doc("Rental Dispatch", doc.name).cancel()

	def test_movement_cannot_be_cancelled_directly(self):
		agreement = approved_agreement(self.customer, self.asset)
		doc = dispatch(agreement)
		with self.assertRaisesRegex(frappe.ValidationError, "Cancel that document instead"):
			frappe.get_doc("Asset Movement", doc.asset_movement).cancel()

	def test_machine_on_hire_cannot_be_moved_by_hand(self):
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement)
		movement = frappe.get_doc({
			"doctype": "Asset Movement", "company": self.company, "purpose": "Transfer",
			"transaction_date": now_datetime(),
			"assets": [{"asset": self.asset, "source_location": self.site, "target_location": self.yard}],
		})
		with self.assertRaisesRegex(frappe.ValidationError, "Move hired equipment"):
			movement.insert(ignore_permissions=True)

	def test_agreement_cannot_be_cancelled_once_dispatched(self):
		"""VAL-22."""
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement)
		with self.assertRaisesRegex(frappe.ValidationError, "still on hire"):
			frappe.get_doc("Rental Agreement", agreement.name).cancel()

	def test_meter_cannot_run_backwards(self):
		agreement = approved_agreement(self.customer, self.asset)
		frappe.db.set_value("Asset", self.asset, "al_last_meter_reading", 500)
		with self.assertRaisesRegex(frappe.ValidationError, "below the last recorded reading"):
			dispatch(agreement)
