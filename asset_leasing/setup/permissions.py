"""P1-14 - give the six leasing roles access to the standard DocTypes they use.

IMPORTANT Frappe behaviour, verified in frappe/permissions.py::get_valid_perms
(lines 514-517): if ANY Custom DocPerm row exists for a DocType, the standard
DocPerm rows for that DocType are ignored completely. Inserting Custom DocPerm
rows directly would therefore strip Accounts Manager, Accounts User and every
other ERPNext role off Sales Invoice.

frappe.permissions.add_permission() is the safe path: it calls
setup_custom_perms() first, which copies every existing standard DocPerm into
Custom DocPerm before adding the new rule. Existing roles are preserved.
Never insert Custom DocPerm directly.
"""

import frappe
from frappe.permissions import add_permission, update_permission_property

HIRE_DESK = "Leasing Hire Desk"
YARD = "Leasing Yard Supervisor"
TECH = "Leasing Maintenance Technician"
FINANCE = "Leasing Finance"
MANAGER = "Leasing Manager"
MANAGEMENT = "Leasing Management"

R = {"read": 1}
RW = {"read": 1, "write": 1}
CRW = {"read": 1, "write": 1, "create": 1}
CR = {"read": 1, "create": 1}
CRWS = {"read": 1, "write": 1, "create": 1, "submit": 1}
RWSX = {"read": 1, "write": 1, "submit": 1, "cancel": 1, "amend": 1}
RS = {"read": 1, "submit": 1}

PERMISSIONS = {
	"Asset": {HIRE_DESK: R, YARD: RW, TECH: RW, FINANCE: R, MANAGER: CRW, MANAGEMENT: R},
	"Asset Category": {HIRE_DESK: R, YARD: R, TECH: R, FINANCE: R, MANAGER: CRW, MANAGEMENT: R},
	"Location": {HIRE_DESK: R, YARD: CRW, TECH: R, FINANCE: R, MANAGER: CRW, MANAGEMENT: R},
	"Item": {HIRE_DESK: R, YARD: R, TECH: R, FINANCE: R, MANAGER: CRW, MANAGEMENT: R},
	"Item Price": {HIRE_DESK: R, FINANCE: R, MANAGER: CRW, MANAGEMENT: R},
	"Price List": {HIRE_DESK: R, FINANCE: R, MANAGER: CRW, MANAGEMENT: R},
	"Customer": {HIRE_DESK: CRW, YARD: R, FINANCE: RW, MANAGER: CRW, MANAGEMENT: R},
	"Asset Repair": {HIRE_DESK: R, YARD: CR, TECH: CRWS, FINANCE: R, MANAGER: RWSX, MANAGEMENT: R},
	"Asset Movement": {HIRE_DESK: R, YARD: R, TECH: R, MANAGER: R, MANAGEMENT: R},
	"Sales Invoice": {HIRE_DESK: R, FINANCE: CRWS, MANAGER: RS, MANAGEMENT: R},
	"Asset Leasing Settings": {MANAGEMENT: R},
}

# Commercially sensitive fields sit at permlevel 1. Only these roles read them.
# Asset.al_lifetime_rental_revenue, Customer.al_deposit_held
PERMLEVEL_1 = {
	"Asset": [MANAGER, FINANCE, MANAGEMENT],
	"Customer": [MANAGER, FINANCE, MANAGEMENT],
}


def _apply(doctype, role, ptypes, permlevel=0):
	if not frappe.db.exists("DocType", doctype):
		return 0
	if not frappe.db.exists("Role", role):
		return 0
	# add_permission copies standard perms into Custom DocPerm before adding,
	# so nothing existing is lost.
	add_permission(doctype, role, permlevel)
	for ptype, value in ptypes.items():
		update_permission_property(doctype, role, permlevel, ptype, value, validate=False)
	return 1


def setup_permissions():
	applied = 0
	for doctype, roles in PERMISSIONS.items():
		for role, ptypes in roles.items():
			applied += _apply(doctype, role, ptypes)

	for doctype, roles in PERMLEVEL_1.items():
		for role in roles:
			applied += _apply(doctype, role, {"read": 1}, permlevel=1)

	frappe.db.commit()
	frappe.clear_cache()
	return applied
