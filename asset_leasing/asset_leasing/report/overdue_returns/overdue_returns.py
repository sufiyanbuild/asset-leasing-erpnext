"""AL-26 - equipment past its expected return plus the grace days, worst first."""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from asset_leasing.asset_leasing.report.equipment_on_hire import equipment_on_hire
from asset_leasing.reports_common import require
from asset_leasing.rental import pricing


def execute(filters=None):
	filters = frappe._dict(filters or {})
	require(filters, "company")
	data = equipment_on_hire.rows(filters.company, filters.customer, overdue_only=True)
	priced = pricing.policy_ready()
	for row in data:
		row["rent_to_date"] = None
		row["surcharge_accrued"] = None
		if priced:
			hire = pricing.price_hire(row["monthly_rate"], row["dispatched"], now_datetime())
			row["rent_to_date"] = hire.amount
			late = pricing.overdue_days(row["expected_return"], now_datetime())
			row["surcharge_accrued"] = pricing.overdue_surcharge(flt(row["monthly_rate"]) / hire.divisor, late)
	columns = equipment_on_hire.columns() + [
		{"label": _("Rent Accrued to Date"), "fieldname": "rent_to_date", "fieldtype": "Currency", "width": 150},
		{"label": _("Surcharge Accrued"), "fieldname": "surcharge_accrued", "fieldtype": "Currency", "width": 140},
	]
	message = None if priced else _("Accrued amounts need the pro-rata policy to be confirmed in Asset Leasing Settings.")
	return columns, data, message
