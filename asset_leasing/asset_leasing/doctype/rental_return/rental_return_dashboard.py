from frappe import _


def get_data():
	return {
		"fieldname": "al_rental_return",
		"non_standard_fieldnames": {"Asset Movement": "reference_name"},
		"internal_links": {
			"Rental Agreement": "rental_agreement",
			"Rental Dispatch": "rental_dispatch",
			"Asset": ["items", "asset"],
		},
		"transactions": [
			{"label": _("Hire"), "items": ["Rental Agreement", "Rental Dispatch"]},
			{"label": _("Equipment"), "items": ["Asset", "Asset Movement", "Asset Repair"]},
			{"label": _("Billing"), "items": ["Sales Invoice"]},
		],
	}
