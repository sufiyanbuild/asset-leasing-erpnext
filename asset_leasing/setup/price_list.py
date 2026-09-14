"""The single rental price list.

Q-01 confirmed a fixed monthly rate as the only commercial rate, so exactly one
price list exists. No daily or weekly lists are created, by design.
"""

import frappe

MONTHLY_PRICE_LIST = "Rental - Monthly"


def create_price_list(currency="INR"):
	if frappe.db.exists("Price List", MONTHLY_PRICE_LIST):
		return None
	frappe.get_doc({
		"doctype": "Price List",
		"price_list_name": MONTHLY_PRICE_LIST,
		"selling": 1,
		"buying": 0,
		"enabled": 1,
		"currency": currency,
	}).insert(ignore_permissions=True)
	return MONTHLY_PRICE_LIST
