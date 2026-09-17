"""AL-19 - moving hired equipment between customer sites."""

import frappe
from frappe.utils import add_to_date, now_datetime

from asset_leasing.asset_leasing.doctype.rental_agreement.rental_agreement import transfer_equipment
from asset_leasing.rental import asset_status as st
from asset_leasing.tests.base import LeasingTestCase
from asset_leasing.tests.fixtures import approved_agreement, dispatch, return_doc


class TestSiteTransfer(LeasingTestCase):
	def test_transfer_keeps_the_hire_and_records_the_move(self):
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement)
		movement = transfer_equipment(agreement.name, self.asset, self.other_site,
									  add_to_date(now_datetime(), hours=-1))
		doc = frappe.get_doc("Asset Movement", movement)
		self.assertEqual((doc.reference_doctype, doc.reference_name), ("Rental Agreement", agreement.name))
		self.assertEqual((doc.assets[0].source_location, doc.assets[0].target_location), (self.site, self.other_site))
		self.assertEqual(frappe.db.get_value("Asset", self.asset, "location"), self.other_site)
		self.assertEqual(self.status(), st.ON_HIRE)

		ret = return_doc(agreement)
		self.assertEqual(ret.items[0].source_location, self.other_site)
		self.assertEqual(frappe.db.get_value("Asset", self.asset, "location"), self.yard)

	def test_transfer_to_a_yard_is_refused(self):
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement)
		with self.assertRaisesRegex(frappe.ValidationError, "Rental Return"):
			transfer_equipment(agreement.name, self.asset, self.yard)

	def test_machine_not_on_hire_cannot_be_transferred(self):
		agreement = approved_agreement(self.customer, self.asset)
		with self.assertRaisesRegex(frappe.ValidationError, "not on hire"):
			transfer_equipment(agreement.name, self.asset, self.other_site)

	def test_transfer_can_be_reversed_while_latest(self):
		agreement = approved_agreement(self.customer, self.asset)
		dispatch(agreement)
		movement = transfer_equipment(agreement.name, self.asset, self.other_site)
		frappe.get_doc("Asset Movement", movement).cancel()
		self.assertEqual(frappe.db.get_value("Asset", self.asset, "location"), self.site)
