"""Rented-asset visual identification - the data behind the picker labels."""

import frappe
from frappe.utils import add_days, nowdate

from asset_leasing.api import get_assets_availability, rentable_asset_query
from asset_leasing.rental import asset_status as st
from asset_leasing.tests.base import LeasingTestCase
from asset_leasing.tests.fixtures import PREFIX, approved_agreement, dispatch, make_agreement


class TestAssetPicker(LeasingTestCase):
	def query(self, txt="", **filters):
		return rentable_asset_query("Asset", txt, "name", 0, 50, {"company": self.company, **filters})

	def row_for(self, rows, asset):
		return next(r for r in rows if r[0] == asset)

	def test_booked_machine_is_labelled_unavailable_and_listed_last(self):
		busy = self.asset
		free = self.new_asset("-free")
		make_agreement(self.customer, busy, "2028-03-01", "2028-03-31", submit=True)
		rows = self.query(txt=PREFIX[:0] or "", start_date="2028-03-10", end_date="2028-03-20")
		names = [r[0] for r in rows]
		self.assertLess(names.index(free), names.index(busy))
		self.assertTrue(self.row_for(rows, free)[1].startswith("✓ Available"))
		label = self.row_for(rows, busy)[1]
		self.assertTrue(label.startswith("✕ Unavailable"), label)
		self.assertIn(self.customer, label)

	def test_same_machine_is_available_outside_the_booking(self):
		make_agreement(self.customer, self.asset, "2028-04-01", "2028-04-30", submit=True)
		rows = self.query(start_date="2028-05-01", end_date="2028-05-10")
		self.assertTrue(self.row_for(rows, self.asset)[1].startswith("✓"))

	def test_open_ended_request_conflicts_with_any_later_booking(self):
		make_agreement(self.customer, self.asset, "2028-06-01", "2028-06-30", submit=True)
		rows = self.query(start_date="2028-05-01", is_open_ended=1)
		self.assertTrue(self.row_for(rows, self.asset)[1].startswith("✕"))

	def test_machine_on_hire_is_flagged_for_a_later_period(self):
		agreement = approved_agreement(self.customer, self.asset, days_ago=2, length=5)
		dispatch(agreement)
		rows = self.query(start_date=add_days(nowdate(), 30), end_date=add_days(nowdate(), 40))
		label = self.row_for(rows, self.asset)[1]
		self.assertTrue(label.startswith("⚠"), label)
		self.assertIn("On Hire", label)

	def test_retired_machine_is_unavailable(self):
		frappe.db.set_value("Asset", self.asset, "al_rental_status", st.RETIRED)
		rows = self.query(start_date="2028-07-01", end_date="2028-07-05")
		self.assertTrue(self.row_for(rows, self.asset)[1].startswith("✕"))

	def test_the_agreement_being_edited_does_not_conflict_with_itself(self):
		agreement = make_agreement(self.customer, self.asset, "2028-08-01", "2028-08-31", submit=True)
		rows = self.query(start_date="2028-08-01", end_date="2028-08-31", agreement=agreement.name)
		self.assertTrue(self.row_for(rows, self.asset)[1].startswith("✓"))

	def test_label_carries_the_machine_name(self):
		rows = self.query(start_date="2028-11-01", end_date="2028-11-05")
		label = self.row_for(rows, self.asset)[1]
		status, name = label.split(" ¦ ")
		self.assertTrue(status.startswith("✓ Available — free"))
		self.assertIn(frappe.db.get_value("Asset", self.asset, "asset_name"), name)

	def test_search_text_filters(self):
		rows = self.query(txt=self.asset)
		self.assertEqual([r[0] for r in rows], [self.asset])

	def test_non_rentable_machines_are_not_offered(self):
		frappe.db.set_value("Asset", self.asset, "al_is_rentable", 0)
		self.assertNotIn(self.asset, [r[0] for r in self.query()])
		frappe.db.set_value("Asset", self.asset, "al_is_rentable", 1)

	def test_labels_for_machines_on_the_form(self):
		make_agreement(self.customer, self.asset, "2028-09-01", "2028-09-30", submit=True)
		out = get_assets_availability([self.asset], "2028-09-15", "2028-09-20")
		self.assertEqual(out[self.asset]["level"], "unavailable")
		self.assertTrue(out[self.asset]["text"].startswith("✕ Unavailable"))

	def test_the_label_never_replaces_validation(self):
		"""The picker only labels; picking a booked machine is still refused on save."""
		make_agreement(self.customer, self.asset, "2028-10-01", "2028-10-31", submit=True)
		with self.assertRaisesRegex(frappe.ValidationError, "already committed"):
			make_agreement(self.other_customer, self.asset, "2028-10-15", "2028-10-20")
