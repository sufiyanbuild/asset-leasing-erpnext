from frappe import _


def get_data():
	return {
		"fieldname": "rental_dispatch",
		"non_standard_fieldnames": {
			"Sales Invoice": "al_rental_dispatch",
			"Asset Movement": "reference_name",
		},
		"internal_links": {"Rental Agreement": "rental_agreement", "Asset": ["items", "asset"]},
		"transactions": [
			{"label": _("Hire"), "items": ["Rental Agreement", "Rental Return"]},
			{"label": _("Equipment"), "items": ["Asset", "Asset Movement"]},
			{"label": _("Billing"), "items": ["Sales Invoice"]},
		],
	}
