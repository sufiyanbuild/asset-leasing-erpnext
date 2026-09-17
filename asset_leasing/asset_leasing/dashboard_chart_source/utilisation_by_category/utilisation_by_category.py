"""Dashboard chart source: Utilisation by Category."""

import frappe
from frappe import _
from frappe.utils import add_months, flt, nowdate
from frappe.utils.dashboard import cache_source


@frappe.whitelist()
@cache_source
def get(chart_name=None, chart=None, no_cache=None, filters=None, from_date=None, to_date=None,
		timespan=None, time_interval=None, heatmap_year=None):
	filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	company = filters.get("company") or frappe.defaults.get_user_default("Company")
	frappe.has_permission("Asset", throw=True)
	from asset_leasing.asset_leasing.report.fleet_utilisation.fleet_utilisation import fleet_utilisation

	result = fleet_utilisation(add_months(nowdate(), -12), nowdate(), company)
	totals = {}
	for row in result["rows"]:
		t = totals.setdefault(row["asset_category"] or _("Uncategorised"), [0.0, 0.0])
		t[0] += row["days_on_hire"]
		t[1] += row["days_in_period"]
	if not totals:
		return {}  # the dashboard shows its own "No Data" state
	return {
		"labels": list(totals),
		"datasets": [{"name": _("Utilisation % (last 12 months)"),
					  "values": [flt(h / d * 100, 1) if d else 0 for h, d in totals.values()]}],
	}
