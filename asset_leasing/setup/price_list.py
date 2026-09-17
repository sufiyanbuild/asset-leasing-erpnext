"""The single rental price list.

Q-01 confirmed a fixed monthly rate as the only commercial rate, so exactly one
price list exists. No daily or weekly lists are created, by design.
"""

import frappe

MONTHLY_PRICE_LIST = "Rental - Monthly"


def create_price_list(currency=None):
	"""Create the monthly rental price list in the default company's currency.

	INR is the fallback because the confirmed client operates in India; a site
	with a default company uses that company's currency instead.
	"""
	if frappe.db.exists("Price List", MONTHLY_PRICE_LIST):
		return None
	if not currency:
		company = frappe.defaults.get_global_default("company")
		currency = (company and frappe.db.get_value("Company", company, "default_currency")) or "INR"
	frappe.get_doc({
		"doctype": "Price List",
		"price_list_name": MONTHLY_PRICE_LIST,
		"selling": 1,
		"buying": 0,
		"enabled": 1,
		"currency": currency,
	}).insert(ignore_permissions=True)
	return MONTHLY_PRICE_LIST
