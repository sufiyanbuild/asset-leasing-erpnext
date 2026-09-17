"""Read-only endpoints used by the forms. Nothing here writes.

The asset picker on a Rental Agreement labels every machine with its
availability for the agreement's dates, using the same availability engine
that validates the agreement on save. The label is a hint; the server-side
check in rental_agreement.py remains the rule.
"""

import frappe
from frappe import _
from frappe.utils import getdate

from asset_leasing.rental import asset_status as st
from asset_leasing.rental.availability import get_conflicting_agreements
from asset_leasing.rental.compliance import EXPIRED, dispatch_blockers

AVAILABLE = "available"
CAUTION = "caution"
UNAVAILABLE = "unavailable"

MARKERS = {AVAILABLE: "✓", CAUTION: "⚠", UNAVAILABLE: "✕"}
EXCLUDED_ASSET_STATUSES = ("Sold", "Scrapped", "Cancelled", "Capitalized")
PICKER_CANDIDATE_LIMIT = 500
# Separates the availability sentence from the machine's name in one
# description column, so a comma in a name cannot break the form's layout.
NAME_SEPARATOR = " ¦ "


def _fmt(date):
	return frappe.format(getdate(date), "Date") if date else _("open-ended")


def assess(asset, start_date=None, end_date=None, exclude_agreement=None, row=None):
	"""Availability of one machine for a period, as a level and a sentence."""
	row = row or frappe.db.get_value(
		"Asset", asset,
		["name", "al_rental_status", "al_current_customer", "al_compliance_status"],
		as_dict=True,
	)
	status = row.al_rental_status or st.AVAILABLE

	if status == st.RETIRED:
		return {"level": UNAVAILABLE, "label": _("Unavailable"), "detail": _("Retired from the hire fleet")}

	if start_date:
		conflicts = get_conflicting_agreements(asset, start_date, end_date, exclude_agreement)
		if conflicts:
			c = conflicts[0]
			state = _("on hire") if c.status in ("Active", "Partially Returned") else _("reserved")
			return {
				"level": UNAVAILABLE,
				"label": _("Unavailable"),
				"detail": _("{0} for {1} on {2} ({3} to {4})").format(
					state, c.customer, c.name, _fmt(c.start_date), _fmt(c.effective_end)
				),
				"agreement": c.name,
			}

	notes = []
	if status != st.AVAILABLE and not (status == st.RESERVED and start_date):
		holder = _(" with {0}").format(row.al_current_customer) if row.al_current_customer else ""
		notes.append(_("currently {0}{1}").format(status, holder))
	elif status == st.RESERVED and not start_date and row.al_current_customer:
		notes.append(_("currently reserved for {0}").format(row.al_current_customer))
	if row.al_compliance_status == EXPIRED:
		notes.append(_("compliance document expired"))
	elif status in (st.AVAILABLE, st.RESERVED):
		blockers = dispatch_blockers(asset)
		if blockers:
			notes.append(blockers[0])

	if notes:
		label = _("Free for these dates") if start_date else _("Check")
		return {"level": CAUTION, "label": label, "detail": "; ".join(notes)}
	if start_date:
		return {"level": AVAILABLE, "label": _("Available"), "detail": _("free {0} to {1}").format(
			_fmt(start_date), _fmt(end_date))}
	return {"level": AVAILABLE, "label": _("Available"), "detail": _("in the yard")}


def describe(result):
	return f"{MARKERS[result['level']]} {result['label']} — {result['detail']}"


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def rentable_asset_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link query for Rental Agreement Item.asset.

	Same eligibility as before (rentable, submitted, not disposed, same
	company), searched on ID, name, item and category, available machines
	listed first, each labelled with its availability for the agreement dates.
	"""
	filters = frappe._dict(filters or {})
	conditions = {
		"al_is_rentable": 1,
		"docstatus": 1,
		"status": ["not in", EXCLUDED_ASSET_STATUSES],
	}
	if filters.get("company"):
		conditions["company"] = filters.company

	or_filters = None
	if txt:
		like = f"%{txt}%"
		or_filters = {
			"name": ["like", like], "asset_name": ["like", like],
			"item_code": ["like", like], "asset_category": ["like", like],
		}

	rows = frappe.get_list(
		"Asset",
		filters=conditions,
		or_filters=or_filters,
		fields=["name", "asset_name", "asset_category", "al_rental_status", "al_current_customer",
				"al_compliance_status"],
		order_by="asset_name asc",
		limit_page_length=PICKER_CANDIDATE_LIMIT,
	)

	start_date = filters.get("start_date")
	end_date = None if filters.get("is_open_ended") else filters.get("end_date")
	exclude = filters.get("agreement")
	rank = {AVAILABLE: 0, CAUTION: 1, UNAVAILABLE: 2}

	scored = []
	for row in rows:
		result = assess(row.name, start_date, end_date, exclude, row=row)
		scored.append((rank[result["level"]], row, result))
	scored.sort(key=lambda s: s[0])

	start, page_len = int(start or 0), int(page_len or 20)
	return [
		(row.name, f"{describe(result)}{NAME_SEPARATOR}{' · '.join(p for p in (row.asset_name, row.asset_category) if p)}")
		for _rank, row, result in scored[start:start + page_len]
	]


@frappe.whitelist()
def get_assets_availability(assets, start_date=None, end_date=None, exclude_agreement=None):
	"""Availability labels for machines already on a form."""
	frappe.has_permission("Rental Agreement", throw=True)
	assets = frappe.parse_json(assets) or []
	out = {}
	for asset in dict.fromkeys(a for a in assets if a):
		if not frappe.has_permission("Asset", "read", asset):
			continue
		result = assess(asset, start_date, end_date or None, exclude_agreement)
		result["text"] = describe(result)
		out[asset] = result
	return out


@frappe.whitelist()
def get_customer_hire_status(customer, company=None):
	"""Advisory hire block and credit position for the agreement form."""
	frappe.has_permission("Rental Agreement", throw=True)
	from asset_leasing.rental.credit import get_credit_position

	blocked, reason = frappe.db.get_value("Customer", customer, ["al_hire_blocked", "al_hire_block_reason"]) or (0, None)
	position = get_credit_position(customer, company) if company else None
	return {
		"blocked": blocked,
		"reason": reason,
		"credit_limit": position.limit if position else None,
		"outstanding": position.outstanding if position else None,
		"exceeded": bool(position and position.exceeded),
	}


@frappe.whitelist()
def utilisation_card(filters=None):
	"""Number card: fleet utilisation for the current month."""
	from frappe.utils import get_first_day, nowdate

	from asset_leasing.asset_leasing.report.fleet_utilisation.fleet_utilisation import fleet_utilisation

	frappe.has_permission("Asset", throw=True)
	result = fleet_utilisation(get_first_day(nowdate()), nowdate())
	return {"value": result["percent"], "fieldtype": "Percent"}


@frappe.whitelist()
def rental_revenue_mtd_card(filters=None):
	from frappe.utils import get_first_day, nowdate

	frappe.has_permission("Sales Invoice", throw=True)
	value = frappe.db.sql(
		"""select coalesce(sum(base_net_total), 0) from `tabSales Invoice`
		where docstatus = 1 and al_invoice_purpose = 'Rental' and posting_date between %s and %s""",
		(get_first_day(nowdate()), nowdate()),
	)[0][0]
	return {"value": value, "fieldtype": "Currency"}
