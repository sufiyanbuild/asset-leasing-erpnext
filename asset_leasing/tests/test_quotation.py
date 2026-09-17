"""AL-06 - a rental quotation becomes a Rental Agreement."""

import frappe
from frappe.utils import add_days, nowdate

from asset_leasing.asset_leasing.doctype.rental_agreement.rental_agreement import make_rental_agreement
from asset_leasing.tests.base import LeasingTestCase


class TestQuotationToAgreement(LeasingTestCase):
	def test_quotation_maps_customer_site_and_lines(self):
		rental_item = frappe.db.get_value("Asset", self.asset, "al_rental_item")
		quotation = frappe.get_doc({
			"doctype": "Quotation", "quotation_to": "Customer", "party_name": self.customer,
			"company": self.company, "transaction_date": nowdate(), "valid_till": add_days(nowdate(), 10),
			"al_is_rental": 1, "al_site_location": self.site, "al_expected_hire_days": 10,
			"selling_price_list": "Rental - Monthly",
			"items": [{"item_code": rental_item, "qty": 2, "rate": 42000}],
		}).insert(ignore_permissions=True)
		quotation.submit()

		agreement = make_rental_agreement(quotation.name)
		self.assertEqual((agreement.customer, agreement.site_location, agreement.quotation),
						 (self.customer, self.site, quotation.name))
		self.assertEqual(len(agreement.items), 2, "one line per quoted unit")
		self.assertEqual({(r.rental_item, r.monthly_rate) for r in agreement.items}, {(rental_item, 42000)})
		self.assertEqual(frappe.utils.date_diff(agreement.expected_end_date, agreement.start_date), 9)

		second = self.new_asset("-2")
		agreement.items[0].asset = self.asset
		agreement.items[1].asset = second
		agreement.insert(ignore_permissions=True)
		self.assertEqual(agreement.items[0].monthly_rate, 42000, "the quoted rate is kept")

	def test_draft_quotation_cannot_convert(self):
		quotation = frappe.get_doc({
			"doctype": "Quotation", "quotation_to": "Customer", "party_name": self.customer,
			"company": self.company, "transaction_date": nowdate(),
			"items": [{"item_code": frappe.db.get_value("Asset", self.asset, "al_rental_item"), "qty": 1, "rate": 1}],
		}).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			make_rental_agreement(quotation.name)
