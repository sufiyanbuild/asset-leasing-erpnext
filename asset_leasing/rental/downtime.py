"""Downtime credit arithmetic (AL-18). Policy-free.

Only an approved (submitted) Rental Downtime Log with Is Creditable ticked
reduces the chargeable duration. Draft, pending and rejected logs are kept for
analysis and never touch a bill.

This module converts approved downtime into days. How those days then round,
and whether a minimum applies, is Q-15 / Q-16 and lives in pricing.py behind
the pricing gate.
"""

import frappe
from frappe.utils import flt, get_datetime


def approved_logs(agreement, asset):
	return frappe.get_all(
		"Rental Downtime Log",
		filters={"rental_agreement": agreement, "asset": asset, "docstatus": 1, "is_creditable": 1},
		fields=["name", "from_datetime", "to_datetime"],
		order_by="from_datetime asc",
	)


def overlap_hours(a_start, a_end, b_start, b_end):
	start = max(get_datetime(a_start), get_datetime(b_start))
	end = min(get_datetime(a_end), get_datetime(b_end))
	if end <= start:
		return 0.0
	return (end - start).total_seconds() / 3600.0


def creditable_downtime_days(agreement, asset, window_start, window_end):
	"""Approved creditable downtime inside the hire window, in days."""
	hours = sum(
		overlap_hours(log.from_datetime, log.to_datetime, window_start, window_end)
		for log in approved_logs(agreement, asset)
	)
	return flt(hours / 24.0, 6)
