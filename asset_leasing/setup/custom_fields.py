"""P1 custom fields - the Asset extension layer.

Every field is prefixed al_ so ownership is unambiguous on a site that may host
more than one app. All insert_after anchors were verified against the live
schema on leasing.local before this was written.

Split into two dicts by phase, because a Link field cannot be created before
its target DocType exists - Frappe validates options at install time.

    P1_CUSTOM_FIELDS - targets that already existed (Item, Location, Customer...)
    P2_CUSTOM_FIELDS - targets Rental Agreement, created in P2

Still deferred:

    Subscription.al_rental_agreement  -> Rental Agreement   (P6, with Subscription work)
    Asset Repair.al_rental_return     -> Rental Return      (P4)

Also deliberately absent, because standard ERPNext already provides them:

    Item.asset_category          - standard, Link to Asset Category
    Sales Invoice.from_date/to_date - standard billing period
    Asset insurance_* fields     - standard
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

RENTAL_STATUSES = [
	"Available", "Reserved", "On Hire", "In Transit",
	"Under Inspection", "Under Repair", "Retired",
]

IS_RENTABLE = "eval:doc.al_is_rentable"

P1_CUSTOM_FIELDS = {
	# ---------------------------------------------- P1-01, 02, 04, 05, 06, 07
	"Asset": [
		{"fieldname": "al_rental_tab", "label": "Rental", "fieldtype": "Tab Break",
		 "insert_after": "booked_fixed_asset"},
		{"fieldname": "al_rental_section", "label": "Hire Configuration",
		 "fieldtype": "Section Break", "insert_after": "al_rental_tab"},
		{"fieldname": "al_is_rentable", "label": "Available for Rental", "fieldtype": "Check",
		 "default": "0", "insert_after": "al_rental_section", "in_standard_filter": 1,
		 "description": "Tick to make this machine available for hire. Requires a rental charge item and a home yard."},
		{"fieldname": "al_rental_item", "label": "Rental Charge Item", "fieldtype": "Link",
		 "options": "Item", "insert_after": "al_is_rentable",
		 "depends_on": IS_RENTABLE, "mandatory_depends_on": IS_RENTABLE,
		 "description": "The non-stock service item used to bill rent. Must never be a fixed-asset item."},
		{"fieldname": "al_base_location", "label": "Home / Yard Location", "fieldtype": "Link",
		 "options": "Location", "insert_after": "al_rental_item",
		 "depends_on": IS_RENTABLE, "mandatory_depends_on": IS_RENTABLE,
		 "description": "Where this machine returns to when off hire."},
		{"fieldname": "al_rental_cb", "fieldtype": "Column Break", "insert_after": "al_base_location"},
		{"fieldname": "al_rental_status", "label": "Rental Status", "fieldtype": "Select",
		 "options": "\n".join(RENTAL_STATUSES), "default": "Available", "read_only": 1,
		 "insert_after": "al_rental_cb", "depends_on": IS_RENTABLE,
		 "in_list_view": 1, "in_standard_filter": 1,
		 "description": "Operational state, separate from the accounting status above. Set only by dispatch and return."},
		{"fieldname": "al_current_customer", "label": "Currently With", "fieldtype": "Link",
		 "options": "Customer", "read_only": 1, "insert_after": "al_rental_status",
		 "depends_on": IS_RENTABLE},

		{"fieldname": "al_meter_section", "label": "Meter & Compliance", "fieldtype": "Section Break",
		 "insert_after": "al_current_customer", "depends_on": IS_RENTABLE},
		{"fieldname": "al_meter_uom", "label": "Meter Unit", "fieldtype": "Select",
		 "options": "\nHours\nKilometres", "insert_after": "al_meter_section",
		 "description": "No default: an excavator is metered in hours, a tipper in kilometres."},
		{"fieldname": "al_last_meter_reading", "label": "Last Meter Reading", "fieldtype": "Float",
		 "precision": "1", "read_only": 1, "insert_after": "al_meter_uom"},
		{"fieldname": "al_compliance_cb", "fieldtype": "Column Break",
		 "insert_after": "al_last_meter_reading"},
		{"fieldname": "al_fitness_expiry", "label": "Fitness Certificate Expiry", "fieldtype": "Date",
		 "insert_after": "al_compliance_cb"},
		{"fieldname": "al_permit_expiry", "label": "Permit Expiry", "fieldtype": "Date",
		 "insert_after": "al_fitness_expiry"},
		{"fieldname": "al_pollution_cert_expiry", "label": "Pollution Certificate Expiry",
		 "fieldtype": "Date", "insert_after": "al_permit_expiry"},

		{"fieldname": "al_stats_section", "label": "Hire Statistics", "fieldtype": "Section Break",
		 "insert_after": "al_pollution_cert_expiry", "collapsible": 1, "depends_on": IS_RENTABLE},
		{"fieldname": "al_total_hire_days", "label": "Total Hire Days", "fieldtype": "Float",
		 "precision": "2", "default": "0", "read_only": 1, "insert_after": "al_stats_section"},
		{"fieldname": "al_stats_cb", "fieldtype": "Column Break", "insert_after": "al_total_hire_days"},
		{"fieldname": "al_lifetime_rental_revenue", "label": "Lifetime Rental Revenue",
		 "fieldtype": "Currency", "options": "company:default_currency", "read_only": 1,
		 "permlevel": 1, "insert_after": "al_stats_cb"},
	],

	# ------------------------------------------------------------------ P1-03
	"Location": [
		{"fieldname": "al_location_type", "label": "Location Type", "fieldtype": "Select",
		 "options": "\nOwned Yard\nCustomer Site\nThird Party\nIn Transit",
		 "insert_after": "is_group", "in_list_view": 1, "in_standard_filter": 1,
		 "description": "Distinguishes our own yards from customer sites. Standard Location has no type field."},
	],

	# ------------------------------------------------------------------ P1-02
	"Item": [
		{"fieldname": "al_is_rental_item", "label": "Is Rental Charge Item", "fieldtype": "Check",
		 "default": "0", "insert_after": "is_fixed_asset", "in_standard_filter": 1,
		 "description": "A service item used to bill rent. Cannot be combined with Is Fixed Asset."},
	],

	# ------------------------------------------------------------------ P1-08
	"Customer": [
		{"fieldname": "al_hire_section", "label": "Equipment Hire", "fieldtype": "Section Break",
		 "insert_after": "tax_category", "collapsible": 1},
		{"fieldname": "al_hire_blocked", "label": "Blocked for Hire", "fieldtype": "Check",
		 "default": "0", "insert_after": "al_hire_section",
		 "description": "Independent of the credit limit. A customer can be within limit and still barred."},
		{"fieldname": "al_hire_block_reason", "label": "Reason for Block", "fieldtype": "Small Text",
		 "insert_after": "al_hire_blocked",
		 "depends_on": "eval:doc.al_hire_blocked", "mandatory_depends_on": "eval:doc.al_hire_blocked"},
		{"fieldname": "al_hire_cb", "fieldtype": "Column Break", "insert_after": "al_hire_block_reason"},
		{"fieldname": "al_deposit_held", "label": "Security Deposit Held", "fieldtype": "Currency",
		 "options": "default_currency", "default": "0", "read_only": 1, "permlevel": 1,
		 "insert_after": "al_hire_cb"},
	],

	# ------------------------------------------------------------- P1-13, P1-09
	"Sales Invoice": [
		{"fieldname": "al_invoice_purpose", "label": "Invoice Purpose", "fieldtype": "Select",
		 "options": "Standard\nRental\nDamage Recovery\nTransport\nDeposit Adjustment",
		 "default": "Standard", "insert_after": "is_return", "in_standard_filter": 1,
		 "description": "Standard is the default so non-leasing invoices are unaffected."},
	],
	"Sales Invoice Item": [
		{"fieldname": "al_asset", "label": "Equipment", "fieldtype": "Link", "options": "Asset",
		 "insert_after": "asset",
		 "description": "The machine this line bills. Never populate the Asset field above - that means disposal."},
		{"fieldname": "al_billable_days", "label": "Billable Days", "fieldtype": "Float",
		 "precision": "2", "read_only": 1, "insert_after": "al_asset"},
	],

	# ------------------------------------------------------------------ P1-10
	"Subscription Plan Detail": [
		{"fieldname": "al_asset", "label": "Equipment", "fieldtype": "Link", "options": "Asset",
		 "insert_after": "plan", "in_list_view": 1},
	],

	# ------------------------------------------------------------------ P1-11
	"Asset Repair": [
		{"fieldname": "al_chargeable_to_customer", "label": "Chargeable to Customer",
		 "fieldtype": "Check", "default": "0", "insert_after": "repair_status"},
		{"fieldname": "al_customer", "label": "Chargeable To", "fieldtype": "Link",
		 "options": "Customer", "insert_after": "al_chargeable_to_customer",
		 "depends_on": "eval:doc.al_chargeable_to_customer",
		 "mandatory_depends_on": "eval:doc.al_chargeable_to_customer"},
	],

	# ------------------------------------------------------------------ P1-12
	"Opportunity": [
		{"fieldname": "al_is_rental_enquiry", "label": "Is Rental Enquiry", "fieldtype": "Check",
		 "default": "0", "insert_after": "opportunity_type", "in_standard_filter": 1},
		{"fieldname": "al_required_from", "label": "Equipment Required From", "fieldtype": "Date",
		 "insert_after": "al_is_rental_enquiry", "depends_on": "eval:doc.al_is_rental_enquiry"},
		{"fieldname": "al_required_days", "label": "Expected Hire Days", "fieldtype": "Int",
		 "insert_after": "al_required_from", "depends_on": "eval:doc.al_is_rental_enquiry"},
	],
	"Quotation": [
		{"fieldname": "al_is_rental", "label": "Is Rental Quotation", "fieldtype": "Check",
		 "default": "0", "insert_after": "order_type", "in_standard_filter": 1},
		{"fieldname": "al_site_location", "label": "Site Location", "fieldtype": "Link",
		 "options": "Location", "insert_after": "al_is_rental",
		 "depends_on": "eval:doc.al_is_rental"},
		{"fieldname": "al_expected_hire_days", "label": "Expected Hire Days", "fieldtype": "Int",
		 "insert_after": "al_site_location", "depends_on": "eval:doc.al_is_rental"},
	],
}


# ---------------------------------------------------------------- P2 fields
# These link to Rental Agreement, so they can only exist once P2 has created it.
P2_CUSTOM_FIELDS = {
	"Asset": [
		{"fieldname": "al_current_agreement", "label": "Current Agreement", "fieldtype": "Link",
		 "options": "Rental Agreement", "read_only": 1, "insert_after": "al_current_customer",
		 "depends_on": IS_RENTABLE,
		 "description": "The agreement currently holding this machine. Set on approval, cleared on return."},
	],
	"Sales Invoice": [
		{"fieldname": "al_rental_agreement", "label": "Rental Agreement", "fieldtype": "Link",
		 "options": "Rental Agreement", "insert_after": "al_invoice_purpose",
		 "in_standard_filter": 1},
	],
}

# Everything the app owns, in dependency order.
CUSTOM_FIELDS = {**P1_CUSTOM_FIELDS}
for _dt, _fields in P2_CUSTOM_FIELDS.items():
	CUSTOM_FIELDS.setdefault(_dt, [])
	CUSTOM_FIELDS[_dt] = CUSTOM_FIELDS[_dt] + _fields


def create_al_custom_fields():
	"""Idempotent. Safe to run on every migrate.

	P2 fields are skipped while Rental Agreement does not exist, so this stays
	safe to call during a partial install.
	"""
	payload = {dt: list(fields) for dt, fields in P1_CUSTOM_FIELDS.items()}

	if frappe.db.exists("DocType", "Rental Agreement"):
		for dt, fields in P2_CUSTOM_FIELDS.items():
			payload.setdefault(dt, [])
			payload[dt] = payload[dt] + fields

	create_custom_fields(payload, update=True)
	frappe.db.commit()
	return sum(len(v) for v in payload.values())
