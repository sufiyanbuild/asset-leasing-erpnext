"""Daily scheduled jobs (Section 12.2).

Each job is idempotent, touches only derived fields, and never posts to the
ledger.

Not scheduled: raise_periodic_hire_invoices. Interim invoicing of long-running
short-term hires needs Q-11 (after how many days), which is still open.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, now_datetime, nowdate

from asset_leasing.rental import asset_status as st
from asset_leasing.rental import billing, lifecycle
from asset_leasing.rental.compliance import compliance_status
from asset_leasing.rental.pricing import elapsed_days

SETTINGS = "Asset Leasing Settings"


def flag_overdue_returns(today=None):
	"""AL-26 - mark agreements whose equipment is past its expected return.

	Overdue means expected end date plus the grace days has passed with any
	line still On Hire. Open-ended hires are never overdue. The flag is raised
	once; the timeline comment and the notification fire on that first
	detection only.
	"""
	today = getdate(today or nowdate())
	grace = int(frappe.db.get_single_value(SETTINGS, "overdue_grace_days") or 0)
	flagged = []

	candidates = frappe.get_all(
		"Rental Agreement",
		filters={"docstatus": 1, "status": ["in", ["Active", "Partially Returned"]], "is_open_ended": 0},
		fields=["name", "expected_end_date", "is_overdue"],
	)
	for row in candidates:
		on_hire = frappe.db.exists(
			"Rental Agreement Item", {"parent": row.name, "line_status": lifecycle.ON_HIRE}
		)
		overdue = bool(on_hire and row.expected_end_date and getdate(add_days(row.expected_end_date, grace)) < today)
		if overdue and not row.is_overdue:
			frappe.db.set_value("Rental Agreement", row.name, {"is_overdue": 1, "overdue_since": today})
			doc = frappe.get_doc("Rental Agreement", row.name)
			doc.add_comment(
				"Info",
				_("Overdue: equipment was due back by {0} ({1} grace day(s)) and is still on hire.").format(
					frappe.format(row.expected_end_date, "Date"), grace
				),
			)
			doc.run_method("al_overdue_detected")
			flagged.append(row.name)
		elif not overdue and row.is_overdue:
			frappe.db.set_value("Rental Agreement", row.name, {"is_overdue": 0, "overdue_since": None})

	stale = frappe.get_all(
		"Rental Agreement",
		filters={"is_overdue": 1, "status": ["not in", ["Active", "Partially Returned"]]},
		pluck="name",
	)
	for name in stale:
		frappe.db.set_value("Rental Agreement", name, {"is_overdue": 0, "overdue_since": None})
	return flagged


def scan_compliance_expiry(today=None):
	"""AL-22 - refresh each machine's compliance flag (Valid / Expiring Soon / Expired).

	The warning notifications are standard Notification records; dispatch is
	blocked by the dispatch controller once a document has expired.
	"""
	changed = []
	for asset in frappe.get_all("Asset", filters={"al_is_rentable": 1, "docstatus": 1},
								fields=["name", "al_compliance_status"]):
		status = compliance_status(asset.name, today)
		if (asset.al_compliance_status or "") != status:
			frappe.db.set_value("Asset", asset.name, "al_compliance_status", status, update_modified=False)
			changed.append(asset.name)
	return changed


def refresh_utilisation_cache():
	"""AL-28 / AL-29 - hire days and rental revenue per machine, from the documents."""
	now = now_datetime()
	assets = frappe.get_all("Asset", filters={"al_is_rentable": 1, "docstatus": 1}, pluck="name")
	lines = frappe.get_all(
		"Rental Agreement Item",
		filters={"asset": ["in", assets or [""]], "docstatus": 1,
				 "line_status": ["in", [lifecycle.ON_HIRE, lifecycle.RETURNED]]},
		fields=["asset", "dispatch_datetime", "return_datetime"],
	)
	days = dict.fromkeys(assets, 0.0)
	for line in lines:
		if line.dispatch_datetime:
			days[line.asset] += elapsed_days(line.dispatch_datetime, line.return_datetime or now)
	for asset, total in days.items():
		frappe.db.set_value("Asset", asset, "al_total_hire_days", flt(total, 2), update_modified=False)
	billing.update_asset_revenue(assets)


def reconcile_asset_status():
	"""Self-healing sweep: report, never correct, machines whose status disagrees
	with their documents."""
	problems = []
	for asset in frappe.get_all(
		"Asset", filters={"al_is_rentable": 1, "docstatus": 1},
		fields=["name", "al_rental_status", "al_current_agreement"],
	):
		on_hire = frappe.get_all(
			"Rental Agreement Item",
			filters={"asset": asset.name, "docstatus": 1, "line_status": lifecycle.ON_HIRE},
			pluck="parent",
		)
		status = asset.al_rental_status or st.AVAILABLE
		claim = lifecycle.get_next_claim(asset.name)

		if on_hire and status not in (st.ON_HIRE, st.IN_TRANSIT):
			problems.append(_("{0} is {1} but on hire under {2}").format(asset.name, status, ", ".join(on_hire)))
		elif len(on_hire) > 1:
			problems.append(_("{0} is on hire under more than one agreement: {1}").format(asset.name, ", ".join(on_hire)))
		elif not on_hire and status in (st.ON_HIRE, st.IN_TRANSIT):
			problems.append(_("{0} is {1} but no agreement has it on hire").format(asset.name, status))
		elif on_hire and asset.al_current_agreement != on_hire[0]:
			problems.append(_("{0} is on hire under {1} but shows {2}").format(
				asset.name, on_hire[0], asset.al_current_agreement or "-"))
		elif not on_hire and status == st.RESERVED and not claim:
			problems.append(_("{0} is Reserved but no approved booking holds it").format(asset.name))
		elif not on_hire and status == st.AVAILABLE and claim:
			problems.append(_("{0} is Available but {1} holds it").format(asset.name, claim.name))

	if problems:
		frappe.log_error(
			title=_("Asset Leasing: rental status discrepancies"),
			message="\n".join(problems),
		)
	return problems
