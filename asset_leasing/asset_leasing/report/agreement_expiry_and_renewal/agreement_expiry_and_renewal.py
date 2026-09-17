"""AL-27 - agreements ending soon, with their value, for renewal pursuit."""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, getdate, nowdate

from asset_leasing.reports_common import require


def execute(filters=None):
	filters = frappe._dict(filters or {})
	require(filters, "company")
	today = getdate(nowdate())
	horizon = add_days(today, cint(filters.days if filters.days is not None else 30))
	conditions = {
		"company": filters.company, "docstatus": 1, "is_open_ended": 0,
		"status": ["in", ["Approved", "Active", "Partially Returned"]],
		"expected_end_date": ["<=", horizon],
	}
	if filters.customer:
		conditions["customer"] = filters.customer
	agreements = frappe.get_all(
		"Rental Agreement", filters=conditions,
		fields=["name", "customer", "agreement_type", "status", "site_location", "start_date",
				"expected_end_date", "estimated_rental_value", "subscription", "is_overdue", "currency"],
		order_by="expected_end_date asc",
	)
	rows = []
	for a in agreements:
		machines = frappe.get_all("Rental Agreement Item", filters={"parent": a.name}, pluck="asset")
		rows.append({**a, "days_to_expiry": date_diff(a.expected_end_date, today), "machines": ", ".join(machines)})
	columns = [
		{"label": _("Agreement"), "fieldname": "name", "fieldtype": "Link", "options": "Rental Agreement", "width": 130},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 180},
		{"label": _("Type"), "fieldname": "agreement_type", "fieldtype": "Data", "width": 140},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
		{"label": _("Site"), "fieldname": "site_location", "fieldtype": "Link", "options": "Location", "width": 160},
		{"label": _("Start"), "fieldname": "start_date", "fieldtype": "Date", "width": 100},
		{"label": _("Ends"), "fieldname": "expected_end_date", "fieldtype": "Date", "width": 100},
		{"label": _("Days to Expiry"), "fieldname": "days_to_expiry", "fieldtype": "Int", "width": 110},
		{"label": _("Equipment"), "fieldname": "machines", "fieldtype": "Data", "width": 220},
		{"label": _("Estimated Value"), "fieldname": "estimated_rental_value", "fieldtype": "Currency", "options": "currency", "width": 130},
		{"label": _("Subscription"), "fieldname": "subscription", "fieldtype": "Link", "options": "Subscription", "width": 150},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "hidden": 1},
	]
	return columns, rows
