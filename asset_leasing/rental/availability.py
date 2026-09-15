"""Equipment availability and double-booking prevention.

ERPNext has no concept of an asset being committed for a date range, so nothing
in the standard product prevents the same machine being promised to two
customers. This module supplies that.

The overlap semantics are carried forward from the crm.local prototype's
"Rental Contract - Validate Equipment" script, which had this right: an
agreement with no end date runs open-ended and therefore overlaps everything
after its start.
"""

import frappe
from frappe import _
from frappe.utils import getdate

# Agreements in these states hold a claim on a machine. Closed and Cancelled
# agreements release it.
BLOCKING_STATUSES = ("Approved", "Active", "Partially Returned")


def periods_overlap(a_start, a_end, b_start, b_end):
	"""True when two date ranges intersect. A missing end date means open-ended."""
	if a_end and b_start and getdate(b_start) > getdate(a_end):
		return False
	if b_end and a_start and getdate(a_start) > getdate(b_end):
		return False
	return True


def get_conflicting_agreements(asset, start_date, end_date, exclude_agreement=None):
	"""Submitted agreements that already claim this asset over an overlapping period."""
	if not asset or not start_date:
		return []

	rows = frappe.get_all(
		"Rental Agreement Item",
		filters={"asset": asset, "docstatus": 1, "line_status": ["!=", "Cancelled"]},
		fields=["parent"],
		distinct=True,
	)

	conflicts = []
	seen = set()
	for row in rows:
		name = row.parent
		if name in seen or name == exclude_agreement:
			continue
		seen.add(name)

		agreement = frappe.db.get_value(
			"Rental Agreement",
			name,
			["name", "customer", "status", "start_date", "expected_end_date",
			 "actual_end_date", "is_open_ended"],
			as_dict=True,
		)
		if not agreement or agreement.status not in BLOCKING_STATUSES:
			continue

		# An open-ended agreement has no end until the machine actually comes back.
		other_end = agreement.actual_end_date or (
			None if agreement.is_open_ended else agreement.expected_end_date
		)
		if periods_overlap(start_date, end_date, agreement.start_date, other_end):
			agreement["effective_end"] = other_end
			conflicts.append(agreement)

	return conflicts


def assert_available(asset, start_date, end_date, exclude_agreement=None, row_idx=None):
	"""Raise when the asset is already committed over the requested period."""
	conflicts = get_conflicting_agreements(asset, start_date, end_date, exclude_agreement)
	if not conflicts:
		return

	first = conflicts[0]
	to_text = frappe.format(first.effective_end, "Date") if first.effective_end else _("open-ended")
	frappe.throw(
		_("{0}Equipment <b>{1}</b> is already committed to <b>{2}</b> on agreement "
		  "<b>{3}</b> for an overlapping period ({4} to {5}).").format(
			_("Row #{0}: ").format(row_idx) if row_idx else "",
			asset, first.customer, first.name,
			frappe.format(first.start_date, "Date"), to_text,
		),
		title=_("Equipment Already Booked"),
	)


@frappe.whitelist()
def get_asset_availability(asset, start_date, end_date=None, exclude_agreement=None):
	"""Read-only helper for the form. Never mutates."""
	frappe.has_permission("Rental Agreement", throw=True)
	conflicts = get_conflicting_agreements(asset, start_date, end_date, exclude_agreement)
	return {
		"available": not conflicts,
		"conflicts": [
			{"agreement": c.name, "customer": c.customer, "from": str(c.start_date),
			 "to": str(c.effective_end) if c.effective_end else None}
			for c in conflicts
		],
	}
