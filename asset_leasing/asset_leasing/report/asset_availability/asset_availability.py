"""AL-04 - "can we supply next Tuesday?" Bookings, maintenance and repairs per machine."""

import frappe
from frappe import _
from frappe.utils import getdate

from asset_leasing.api import AVAILABLE, UNAVAILABLE, assess
from asset_leasing.reports_common import rentable_assets, require
from asset_leasing.rental.availability import get_conflicting_agreements
from asset_leasing.rental.compliance import open_repairs


def execute(filters=None):
	filters = frappe._dict(filters or {})
	require(filters, "company", "from_date", "to_date")
	if getdate(filters.to_date) < getdate(filters.from_date):
		frappe.throw(_("To Date cannot be before From Date."))
	rows = []
	for a in rentable_assets(filters.company, filters.asset_category):
		result = assess(a.name, filters.from_date, filters.to_date, row=a)
		bookings = get_conflicting_agreements(a.name, filters.from_date, filters.to_date)
		maintenance = frappe.get_all(
			"Asset Maintenance Log",
			filters={"asset_name": a.name, "docstatus": 0,
					 "due_date": ["between", [filters.from_date, filters.to_date]]},
			pluck="name",
		)
		rows.append({
			"asset": a.name, "asset_name": a.asset_name, "asset_category": a.asset_category,
			"rental_status": a.al_rental_status, "location": a.location,
			"availability": {AVAILABLE: _("Available"), UNAVAILABLE: _("Booked")}.get(result["level"], _("Check")),
			"detail": result["detail"],
			"bookings": ", ".join(f"{b.name} ({b.customer})" for b in bookings),
			"maintenance_due": ", ".join(maintenance),
			"open_repairs": ", ".join(open_repairs(a.name)),
			"compliance": a.al_compliance_status,
		})
	columns = [
		{"label": _("Equipment"), "fieldname": "asset", "fieldtype": "Link", "options": "Asset", "width": 160},
		{"label": _("Name"), "fieldname": "asset_name", "fieldtype": "Data", "width": 160},
		{"label": _("Category"), "fieldname": "asset_category", "fieldtype": "Link", "options": "Asset Category", "width": 120},
		{"label": _("Availability"), "fieldname": "availability", "fieldtype": "Data", "width": 100},
		{"label": _("Detail"), "fieldname": "detail", "fieldtype": "Data", "width": 280},
		{"label": _("Status Now"), "fieldname": "rental_status", "fieldtype": "Data", "width": 110},
		{"label": _("Location"), "fieldname": "location", "fieldtype": "Link", "options": "Location", "width": 150},
		{"label": _("Bookings in Period"), "fieldname": "bookings", "fieldtype": "Data", "width": 220},
		{"label": _("Maintenance Due"), "fieldname": "maintenance_due", "fieldtype": "Data", "width": 150},
		{"label": _("Open Repairs"), "fieldname": "open_repairs", "fieldtype": "Data", "width": 150},
		{"label": _("Compliance"), "fieldname": "compliance", "fieldtype": "Data", "width": 110},
	]
	return columns, rows
