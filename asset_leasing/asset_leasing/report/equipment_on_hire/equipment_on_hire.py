"""AL-26 - the live position: what is out, where, since when, and whether it is late."""

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, getdate, now_datetime, nowdate

from asset_leasing.reports_common import hire_lines, require
from asset_leasing.rental.pricing import elapsed_days


def execute(filters=None):
	filters = frappe._dict(filters or {})
	require(filters, "company")
	return columns(), rows(filters.company, filters.customer)


def columns():
	return [
		{"label": _("Equipment"), "fieldname": "asset", "fieldtype": "Link", "options": "Asset", "width": 160},
		{"label": _("Name"), "fieldname": "asset_name", "fieldtype": "Data", "width": 160},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 180},
		{"label": _("Agreement"), "fieldname": "agreement", "fieldtype": "Link", "options": "Rental Agreement", "width": 130},
		{"label": _("Currently At"), "fieldname": "location", "fieldtype": "Link", "options": "Location", "width": 170},
		{"label": _("Dispatched"), "fieldname": "dispatched", "fieldtype": "Datetime", "width": 150},
		{"label": _("Expected Return"), "fieldname": "expected_return", "fieldtype": "Date", "width": 120},
		{"label": _("Days Out"), "fieldname": "days_out", "fieldtype": "Float", "precision": 1, "width": 90},
		{"label": _("Days Overdue"), "fieldname": "days_overdue", "fieldtype": "Int", "width": 100},
	]


def rows(company, customer=None, overdue_only=False):
	grace = int(frappe.db.get_single_value("Asset Leasing Settings", "overdue_grace_days") or 0)
	today = getdate(nowdate())
	out = []
	for line in hire_lines(company, statuses=("On Hire",), customer=customer):
		overdue = 0
		if line.expected_end_date and not line.is_open_ended:
			overdue = max(0, date_diff(today, add_days(line.expected_end_date, grace)))
		if overdue_only and not overdue:
			continue
		out.append({
			"asset": line.asset, "asset_name": line.asset_name, "customer": line.customer,
			"agreement": line.agreement, "location": frappe.db.get_value("Asset", line.asset, "location"),
			"dispatched": line.dispatch_datetime, "expected_return": line.expected_end_date,
			"days_out": flt(elapsed_days(line.dispatch_datetime, now_datetime()), 1),
			"days_overdue": overdue, "monthly_rate": line.monthly_rate, "currency": line.currency,
		})
	return sorted(out, key=lambda r: -r["days_overdue"]) if overdue_only else out
