"""The six leasing roles from Section 08 of the specification."""

import frappe

ROLES = [
	("Leasing Hire Desk", "Registers hire enquiries, raises Rental Agreements, records downtime."),
	("Leasing Yard Supervisor", "Dispatches and receives equipment, records condition and meter readings."),
	("Leasing Maintenance Technician", "Inspects returned equipment, records damage, maintains service records."),
	("Leasing Finance", "Raises invoices, records payments, manages retention and receivables."),
	("Leasing Manager", "Approves agreements, damage charges and downtime credits."),
	("Leasing Management", "Read-only consolidated visibility across dashboards and reports."),
]


def create_roles():
	created = []
	for role_name, description in ROLES:
		if frappe.db.exists("Role", role_name):
			continue
		frappe.get_doc({
			"doctype": "Role",
			"role_name": role_name,
			"desk_access": 1,
			"search_bar": 1,
			"notifications": 1,
		}).insert(ignore_permissions=True)
		created.append(role_name)
	return created
