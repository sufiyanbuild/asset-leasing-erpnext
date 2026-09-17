"""Safety and compliance checks that decide whether a machine may leave the yard.

VAL-16: plant with expired insurance, fitness or permit is never released - that
is a liability event, not a data-quality one. Overdue preventive maintenance
blocks dispatch when Asset Leasing Settings says so. An open repair job always
blocks (AL-04: nothing is dispatched while under repair).

The pollution certificate is tracked on the Asset but does not block dispatch:
the specification names insurance, fitness and permit only, and Q-21 (whether
these certificates apply to yard-bound plant at all) is still open.
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

SETTINGS = "Asset Leasing Settings"

# (Asset field, label) - the documents whose expiry blocks a dispatch.
BLOCKING_EXPIRY_FIELDS = [
	("insurance_end_date", "Insurance"),
	("al_fitness_expiry", "Fitness Certificate"),
	("al_permit_expiry", "Permit"),
]

EXPIRY_WARNING_DAYS = 30

VALID = "Valid"
EXPIRING = "Expiring Soon"
EXPIRED = "Expired"


def expiry_dates(asset):
	"""(label, date) pairs for an asset name, or for an Asset document in hand."""
	if isinstance(asset, str):
		fields = [f for f, _label in BLOCKING_EXPIRY_FIELDS]
		values = frappe.db.get_value("Asset", asset, fields, as_dict=True) or {}
	else:
		values = asset
	return [(label, values.get(field)) for field, label in BLOCKING_EXPIRY_FIELDS if values.get(field)]


def expired_documents(asset, on_date=None):
	on_date = getdate(on_date or nowdate())
	return [(label, date) for label, date in expiry_dates(asset) if getdate(date) < on_date]


def expiring_documents(asset, on_date=None, days=EXPIRY_WARNING_DAYS):
	on_date = getdate(on_date or nowdate())
	horizon = getdate(add_days(on_date, days))
	return [(label, date) for label, date in expiry_dates(asset) if on_date <= getdate(date) <= horizon]


def compliance_status(asset, on_date=None):
	dates = expiry_dates(asset)
	if not dates:
		return ""
	if expired_documents(asset, on_date):
		return EXPIRED
	if expiring_documents(asset, on_date):
		return EXPIRING
	return VALID


def overdue_maintenance(asset, on_date=None):
	"""Open preventive-maintenance logs that are past due."""
	on_date = getdate(on_date or nowdate())
	logs = frappe.get_all(
		"Asset Maintenance Log",
		filters={"asset_name": asset, "docstatus": 0, "maintenance_status": ["in", ["Planned", "Overdue"]]},
		fields=["name", "task_name", "due_date", "maintenance_status"],
	)
	return [
		log for log in logs
		if log.maintenance_status == "Overdue" or (log.due_date and getdate(log.due_date) < on_date)
	]


def open_repairs(asset):
	return frappe.get_all(
		"Asset Repair",
		filters={"asset": asset, "docstatus": 0, "repair_status": "Pending"},
		pluck="name",
	)


def dispatch_blockers(asset, on_date=None):
	"""Every reason this asset may not be dispatched on the given date."""
	settings = frappe.get_cached_doc(SETTINGS)
	reasons = []

	for label, date in expired_documents(asset, on_date):
		reasons.append(_("{0} expired on {1}").format(label, frappe.format(date, "Date")))

	repairs = open_repairs(asset)
	if repairs:
		reasons.append(_("repair job {0} is still open").format(", ".join(repairs)))

	if settings.block_dispatch_if_maintenance_overdue:
		for log in overdue_maintenance(asset, on_date):
			reasons.append(
				_("maintenance {0} ({1}) was due on {2}").format(
					log.name, log.task_name or "", frappe.format(log.due_date, "Date")
				)
			)
	return reasons


def assert_dispatchable(asset, on_date=None, row_idx=None):
	reasons = dispatch_blockers(asset, on_date)
	if not reasons:
		return
	frappe.throw(
		_("{0}Asset {1} cannot leave the yard: {2}.").format(
			_("Row #{0}: ").format(row_idx) if row_idx else "", asset, "; ".join(reasons)
		),
		title=_("Equipment Not Fit For Dispatch"),
	)
