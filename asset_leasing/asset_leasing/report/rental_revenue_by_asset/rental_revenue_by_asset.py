"""AL-29 - what each machine earned against what it cost."""

import frappe
from frappe import _
from frappe.utils import flt

from asset_leasing.reports_common import invoice_totals_by_asset, rentable_assets, require


def execute(filters=None):
	filters = frappe._dict(filters or {})
	require(filters, "company")
	assets = rentable_assets(filters.company, filters.asset_category)
	names = [a.name for a in assets]
	rent = invoice_totals_by_asset(filters.company, "Rental", filters.from_date, filters.to_date, names)
	damage = invoice_totals_by_asset(filters.company, "Damage Recovery", filters.from_date, filters.to_date, names)
	repairs = _repair_cost(names, filters)
	depreciation = _depreciation(names, filters)
	rows = []
	for a in assets:
		capital = flt(a.total_asset_cost or a.net_purchase_amount)
		income = rent.get(a.name, 0.0) + damage.get(a.name, 0.0)
		net = income - repairs.get(a.name, 0.0) - depreciation.get(a.name, 0.0)
		rows.append({
			"asset": a.name, "asset_name": a.asset_name, "asset_category": a.asset_category,
			"capital_cost": capital, "rental_revenue": rent.get(a.name, 0.0),
			"damage_recovery": damage.get(a.name, 0.0), "repair_cost": repairs.get(a.name, 0.0),
			"depreciation": depreciation.get(a.name, 0.0), "net_contribution": net,
			"return_on_capital": flt(net / capital * 100, 2) if capital else 0,
		})
	columns = [
		{"label": _("Equipment"), "fieldname": "asset", "fieldtype": "Link", "options": "Asset", "width": 160},
		{"label": _("Name"), "fieldname": "asset_name", "fieldtype": "Data", "width": 160},
		{"label": _("Category"), "fieldname": "asset_category", "fieldtype": "Link", "options": "Asset Category", "width": 120},
		{"label": _("Capital Cost"), "fieldname": "capital_cost", "fieldtype": "Currency", "width": 130},
		{"label": _("Rental Revenue"), "fieldname": "rental_revenue", "fieldtype": "Currency", "width": 130},
		{"label": _("Damage Recovered"), "fieldname": "damage_recovery", "fieldtype": "Currency", "width": 130},
		{"label": _("Repair Cost"), "fieldname": "repair_cost", "fieldtype": "Currency", "width": 120},
		{"label": _("Depreciation"), "fieldname": "depreciation", "fieldtype": "Currency", "width": 120},
		{"label": _("Net Contribution"), "fieldname": "net_contribution", "fieldtype": "Currency", "width": 140},
		{"label": _("Return on Capital %"), "fieldname": "return_on_capital", "fieldtype": "Percent", "width": 130},
	]
	return columns, rows, None, None, None, True


def _repair_cost(assets, filters):
	if not assets:
		return {}
	conditions, values = ["asset in %(assets)s", "docstatus = 1"], {"assets": tuple(assets)}
	if filters.from_date:
		conditions.append("date(completion_date) >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.to_date:
		conditions.append("date(completion_date) <= %(to_date)s")
		values["to_date"] = filters.to_date
	rows = frappe.db.sql(
		f"select asset, sum(total_repair_cost) from `tabAsset Repair` where {' and '.join(conditions)} group by asset",
		values,
	)
	return {r[0]: flt(r[1]) for r in rows}


def _depreciation(assets, filters):
	if not assets:
		return {}
	conditions = ["ads.asset in %(assets)s", "ads.docstatus = 1", "ifnull(ds.journal_entry, '') != ''"]
	values = {"assets": tuple(assets)}
	if filters.from_date:
		conditions.append("ds.schedule_date >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.to_date:
		conditions.append("ds.schedule_date <= %(to_date)s")
		values["to_date"] = filters.to_date
	rows = frappe.db.sql(
		f"""select ads.asset, sum(ds.depreciation_amount)
		from `tabDepreciation Schedule` ds join `tabAsset Depreciation Schedule` ads on ads.name = ds.parent
		where {' and '.join(conditions)} group by ads.asset""",
		values,
	)
	return {r[0]: flt(r[1]) for r in rows}
