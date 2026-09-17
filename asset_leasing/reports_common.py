"""Shared helpers for the Asset Leasing script reports."""

import frappe
from frappe import _
from frappe.utils import add_days, flt, get_datetime, getdate, now_datetime


def require(filters, *fields):
	for field in fields:
		if not filters.get(field):
			frappe.throw(_("{0} is required.").format(frappe.unscrub(field)))


def period_bounds(from_date, to_date):
	"""[from 00:00, to+1 00:00) as datetimes."""
	return get_datetime(getdate(from_date)), get_datetime(add_days(getdate(to_date), 1))


def overlap_days(start, end, window_start, window_end):
	if not start:
		return 0.0
	start = max(get_datetime(start), window_start)
	end = min(get_datetime(end) if end else now_datetime(), window_end)
	if end <= start:
		return 0.0
	return (end - start).total_seconds() / 86400.0


def rentable_assets(company, category=None, asset=None):
	filters = {"al_is_rentable": 1, "docstatus": 1, "company": company}
	if category:
		filters["asset_category"] = category
	if asset:
		filters["name"] = asset
	return frappe.get_all(
		"Asset",
		filters=filters,
		fields=["name", "asset_name", "asset_category", "available_for_use_date", "location",
				"al_rental_status", "al_current_customer", "al_current_agreement", "al_compliance_status",
				"net_purchase_amount", "total_asset_cost", "al_rental_item"],
		order_by="asset_name asc",
	)


def invoice_totals_by_asset(company, purpose, from_date=None, to_date=None, assets=None):
	conditions = ["si.docstatus = 1", "si.company = %(company)s", "si.al_invoice_purpose = %(purpose)s",
				  "ifnull(sii.al_asset, '') != ''"]
	values = {"company": company, "purpose": purpose}
	if from_date:
		conditions.append("si.posting_date >= %(from_date)s")
		values["from_date"] = from_date
	if to_date:
		conditions.append("si.posting_date <= %(to_date)s")
		values["to_date"] = to_date
	if assets is not None:
		if not assets:
			return {}
		conditions.append("sii.al_asset in %(assets)s")
		values["assets"] = tuple(assets)
	rows = frappe.db.sql(
		f"""
		select sii.al_asset as asset, sum(sii.base_net_amount) as amount
		from `tabSales Invoice Item` sii join `tabSales Invoice` si on si.name = sii.parent
		where {" and ".join(conditions)}
		group by sii.al_asset
		""",
		values,
		as_dict=True,
	)
	return {r.asset: flt(r.amount) for r in rows}


def hire_lines(company, assets=None, statuses=("On Hire", "Returned"), customer=None):
	conditions = ["ra.docstatus = 1", "ra.company = %(company)s", "rai.line_status in %(statuses)s"]
	values = {"company": company, "statuses": tuple(statuses)}
	if assets is not None:
		if not assets:
			return []
		conditions.append("rai.asset in %(assets)s")
		values["assets"] = tuple(assets)
	if customer:
		conditions.append("ra.customer = %(customer)s")
		values["customer"] = customer
	return frappe.db.sql(
		f"""
		select rai.name as line, rai.asset, rai.asset_name, rai.line_status, rai.dispatch_datetime,
			rai.return_datetime, rai.monthly_rate, rai.billable_days, rai.line_amount, rai.rental_item,
			ra.name as agreement, ra.customer, ra.customer_name, ra.site_location, ra.status,
			ra.agreement_type, ra.start_date, ra.expected_end_date, ra.is_open_ended, ra.currency
		from `tabRental Agreement Item` rai join `tabRental Agreement` ra on ra.name = rai.parent
		where {" and ".join(conditions)}
		order by rai.dispatch_datetime desc
		""",
		values,
		as_dict=True,
	)
