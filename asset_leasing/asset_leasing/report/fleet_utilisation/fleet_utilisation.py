"""AL-28 - share of available days each machine spent on hire."""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, nowdate

from asset_leasing.reports_common import (
	invoice_totals_by_asset, hire_lines, overlap_days, period_bounds, rentable_assets, require,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	require(filters, "company", "from_date", "to_date")
	result = fleet_utilisation(filters.from_date, filters.to_date, filters.company, filters.asset_category)
	columns = [
		{"label": _("Equipment"), "fieldname": "asset", "fieldtype": "Link", "options": "Asset", "width": 170},
		{"label": _("Name"), "fieldname": "asset_name", "fieldtype": "Data", "width": 180},
		{"label": _("Category"), "fieldname": "asset_category", "fieldtype": "Link", "options": "Asset Category", "width": 130},
		{"label": _("Days in Period"), "fieldname": "days_in_period", "fieldtype": "Float", "precision": 1, "width": 110},
		{"label": _("Days on Hire"), "fieldname": "days_on_hire", "fieldtype": "Float", "precision": 1, "width": 110},
		{"label": _("Days Under Repair"), "fieldname": "days_under_repair", "fieldtype": "Float", "precision": 1, "width": 130},
		{"label": _("Utilisation %"), "fieldname": "utilisation", "fieldtype": "Percent", "width": 110},
		{"label": _("Rental Revenue"), "fieldname": "revenue", "fieldtype": "Currency", "width": 130},
	]
	by_category = {}
	for row in result["rows"]:
		c = by_category.setdefault(row["asset_category"] or _("Uncategorised"), [0.0, 0.0])
		c[0] += row["days_on_hire"]
		c[1] += row["days_in_period"]
	chart = {
		"data": {
			"labels": list(by_category),
			"datasets": [{"name": _("Utilisation %"), "values": [
				flt(v[0] / v[1] * 100, 1) if v[1] else 0 for v in by_category.values()
			]}],
		},
		"type": "bar",
	}
	summary = [
		{"label": _("Fleet Utilisation"), "value": result["percent"], "datatype": "Percent",
		 "indicator": "Green" if result["percent"] >= 60 else "Orange"},
		{"label": _("Machines"), "value": len(result["rows"]), "datatype": "Int"},
		{"label": _("Rental Revenue"), "value": sum(r["revenue"] for r in result["rows"]), "datatype": "Currency"},
	]
	return columns, result["rows"], None, chart, summary


def fleet_utilisation(from_date, to_date, company=None, category=None):
	companies = [company] if company else frappe.get_all("Company", pluck="name")
	window_start, window_end = period_bounds(from_date, to_date)
	rows = []
	for comp in companies:
		assets = rentable_assets(comp, category)
		names = [a.name for a in assets]
		hired = {}
		for line in hire_lines(comp, names):
			hired[line.asset] = hired.get(line.asset, 0.0) + overlap_days(
				line.dispatch_datetime, line.return_datetime, window_start, window_end)
		repairs = {}
		for rep in frappe.get_all("Asset Repair", filters={"asset": ["in", names or [""]], "docstatus": ["<", 2]},
								  fields=["asset", "failure_date", "completion_date", "repair_status"]):
			if rep.repair_status == "Cancelled":
				continue
			repairs[rep.asset] = repairs.get(rep.asset, 0.0) + overlap_days(
				rep.failure_date, rep.completion_date, window_start, window_end)
		revenue = invoice_totals_by_asset(comp, "Rental", from_date, to_date, names)
		for a in assets:
			start = max(getdate(from_date), getdate(a.available_for_use_date or from_date))
			end = min(getdate(to_date), getdate(nowdate())) if getdate(from_date) <= getdate(nowdate()) else getdate(to_date)
			days = max(0, date_diff(getdate(to_date), start) + 1)
			on_hire = flt(hired.get(a.name), 2)
			rows.append({
				"asset": a.name, "asset_name": a.asset_name, "asset_category": a.asset_category,
				"days_in_period": days, "days_on_hire": on_hire,
				"days_under_repair": flt(repairs.get(a.name), 2),
				"utilisation": flt(on_hire / days * 100, 1) if days else 0,
				"revenue": flt(revenue.get(a.name)),
			})
	total_days = sum(r["days_in_period"] for r in rows)
	total_hire = sum(r["days_on_hire"] for r in rows)
	return {"rows": rows, "percent": flt(total_hire / total_days * 100, 1) if total_days else 0}
