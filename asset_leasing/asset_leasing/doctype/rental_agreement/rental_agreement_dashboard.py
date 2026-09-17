from frappe import _


def get_data():
	return {
		"fieldname": "rental_agreement",
		"non_standard_fieldnames": {
			"Sales Invoice": "al_rental_agreement",
			"Payment Entry": "al_rental_agreement",
			"Subscription": "al_rental_agreement",
			"Asset Movement": "reference_name",
		},
		"internal_links": {
			"Asset": ["items", "asset"],
			"Quotation": "quotation",
		},
		"transactions": [
			{"label": _("Equipment"), "items": ["Asset", "Rental Dispatch", "Rental Return", "Asset Movement"]},
			{"label": _("Operations"), "items": ["Rental Downtime Log"]},
			{"label": _("Billing"), "items": ["Sales Invoice", "Payment Entry", "Subscription"]},
			{"label": _("Pre-sales"), "items": ["Quotation"]},
		],
	}
