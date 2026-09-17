"""Dashboard chart source: Rental Revenue by Category."""

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
	frappe.has_permission("Sales Invoice", throw=True)
	rows = frappe.db.sql(
		"""select coalesce(a.asset_category, %(none)s), sum(sii.base_net_amount)
		from `tabSales Invoice Item` sii
		join `tabSales Invoice` si on si.name = sii.parent
		join `tabAsset` a on a.name = sii.al_asset
		where si.docstatus = 1 and si.company = %(company)s and si.al_invoice_purpose = 'Rental'
			and si.posting_date >= %(since)s
		group by a.asset_category order by 2 desc""",
		{"company": company, "since": add_months(nowdate(), -12), "none": _("Uncategorised")},
	)
	if not rows:
		return {}  # the dashboard shows its own "No Data" state
	return {
		"labels": [r[0] for r in rows],
		"datasets": [{"name": _("Rental Revenue (last 12 months)"), "values": [flt(r[1]) for r in rows]}],
	}
