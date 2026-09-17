"""AL-29 - every hire of a machine: who, where, how long, what it earned."""

import frappe
from frappe import _
from frappe.utils import flt

from asset_leasing.reports_common import hire_lines, rentable_assets, require
from asset_leasing.rental.pricing import elapsed_days


def execute(filters=None):
	filters = frappe._dict(filters or {})
	require(filters, "company")
	assets = [a.name for a in rentable_assets(filters.company, asset=filters.asset)]
	lines = hire_lines(filters.company, assets, statuses=("Pending Dispatch", "On Hire", "Returned"),
					   customer=filters.customer)
	revenue = _by_line(filters.company, "Rental")
	damage = _damage()
	rows = []
	for line in lines:
		rows.append({
			"asset": line.asset, "asset_name": line.asset_name, "agreement": line.agreement,
			"agreement_status": line.status, "customer": line.customer, "site": line.site_location,
			"line_status": line.line_status, "dispatched": line.dispatch_datetime, "returned": line.return_datetime,
			"days": flt(elapsed_days(line.dispatch_datetime, line.return_datetime), 2)
			if line.dispatch_datetime and line.return_datetime else None,
			"billable_days": line.billable_days, "monthly_rate": line.monthly_rate,
			"revenue": revenue.get((line.agreement, line.asset), 0.0),
			"damage": damage.get((line.agreement, line.asset), 0.0),
		})
	columns = [
		{"label": _("Equipment"), "fieldname": "asset", "fieldtype": "Link", "options": "Asset", "width": 160},
		{"label": _("Name"), "fieldname": "asset_name", "fieldtype": "Data", "width": 150},
		{"label": _("Agreement"), "fieldname": "agreement", "fieldtype": "Link", "options": "Rental Agreement", "width": 130},
		{"label": _("Agreement Status"), "fieldname": "agreement_status", "fieldtype": "Data", "width": 120},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 170},
		{"label": _("Site"), "fieldname": "site", "fieldtype": "Link", "options": "Location", "width": 160},
		{"label": _("Line Status"), "fieldname": "line_status", "fieldtype": "Data", "width": 110},
		{"label": _("Out"), "fieldname": "dispatched", "fieldtype": "Datetime", "width": 150},
		{"label": _("In"), "fieldname": "returned", "fieldtype": "Datetime", "width": 150},
		{"label": _("Days"), "fieldname": "days", "fieldtype": "Float", "precision": 2, "width": 80},
		{"label": _("Billable Days"), "fieldname": "billable_days", "fieldtype": "Float", "precision": 2, "width": 100},
		{"label": _("Monthly Rate"), "fieldname": "monthly_rate", "fieldtype": "Currency", "width": 120},
		{"label": _("Revenue Invoiced"), "fieldname": "revenue", "fieldtype": "Currency", "width": 130},
		{"label": _("Chargeable Damage"), "fieldname": "damage", "fieldtype": "Currency", "width": 130},
	]
	return columns, rows


def _by_line(company, purpose):
	rows = frappe.db.sql(
		"""select si.al_rental_agreement, sii.al_asset, sum(sii.base_net_amount)
		from `tabSales Invoice Item` sii join `tabSales Invoice` si on si.name = sii.parent
		where si.docstatus = 1 and si.company = %s and si.al_invoice_purpose = %s
		group by si.al_rental_agreement, sii.al_asset""",
		(company, purpose),
	)
	return {(r[0], r[1]): flt(r[2]) for r in rows}


def _damage():
	rows = frappe.db.sql(
		"""select rr.rental_agreement, rdi.asset, sum(rdi.estimated_cost)
		from `tabRental Damage Item` rdi join `tabRental Return` rr on rr.name = rdi.parent
		where rr.docstatus = 1 and rdi.chargeable_to_customer = 1
		group by rr.rental_agreement, rdi.asset"""
	)
	return {(r[0], r[1]): flt(r[2]) for r in rows}
