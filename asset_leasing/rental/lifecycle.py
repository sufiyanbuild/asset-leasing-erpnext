"""Derived state: which agreement holds a machine, and where an agreement is.

Two read-only displays are maintained here rather than written ad hoc by each
document:

* Asset.al_current_agreement / al_current_customer, and the Reserved/Available
  half of al_rental_status. These are recomputed from the agreements
  themselves, so approving a later booking, cancelling an earlier one or
  returning a machine always leaves the asset pointing at the claim that
  actually comes next. (The P2 behaviour of "last approval wins" is gone.)

* Rental Agreement.status - Approved, Active, Partially Returned, Closed - which
  is a consequence of the dispatch and return documents, never of a workflow
  action.

The availability engine never reads either display. It reads agreements.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from asset_leasing.rental import asset_status as st
from asset_leasing.rental.availability import BLOCKING_STATUSES

PENDING = "Pending Dispatch"
ON_HIRE = "On Hire"
RETURNED = "Returned"
CANCELLED = "Cancelled"


def get_next_claim(asset):
	"""The earliest approved agreement still waiting to dispatch this asset."""
	rows = frappe.db.sql(
		"""
		select ra.name, ra.customer, ra.start_date
		from `tabRental Agreement Item` rai
		join `tabRental Agreement` ra on ra.name = rai.parent
		where rai.asset = %(asset)s
			and rai.line_status = %(pending)s
			and ra.docstatus = 1
			and ra.status in %(blocking)s
		order by ra.start_date asc, ra.name asc
		limit 1
		""",
		{"asset": asset, "pending": PENDING, "blocking": BLOCKING_STATUSES},
		as_dict=True,
	)
	return rows[0] if rows else None


def refresh_asset_hold(asset, reason=None):
	"""Recompute Reserved / Available and the current-agreement display.

	Only the booking half of the state machine is touched. A machine that is on
	hire, in transit, under inspection, under repair or retired keeps its status;
	those are owned by the documents that put it there.
	"""
	status = st.get_status(asset)
	if status in (st.ON_HIRE, st.IN_TRANSIT):
		return status

	claim = get_next_claim(asset)
	if status not in (st.AVAILABLE, st.RESERVED):
		_set_holder(asset, None, None)
		return status

	if claim:
		if status == st.AVAILABLE:
			st.set_status(
				asset, st.RESERVED,
				reason=reason or _("Reserved for {0} on agreement {1}.").format(claim.customer, claim.name),
			)
		_set_holder(asset, claim.name, claim.customer)
		return st.RESERVED

	if status == st.RESERVED:
		st.set_status(asset, st.AVAILABLE, reason=reason or _("No approved booking remains."))
	_set_holder(asset, None, None)
	return st.AVAILABLE


def set_on_hire_holder(asset, agreement, customer):
	_set_holder(asset, agreement, customer)


def _set_holder(asset, agreement, customer):
	current = frappe.db.get_value("Asset", asset, ["al_current_agreement", "al_current_customer"])
	if tuple(current or (None, None)) == (agreement, customer):
		return
	frappe.db.set_value(
		"Asset", asset,
		{"al_current_agreement": agreement, "al_current_customer": customer},
		update_modified=False,
	)


def refresh_agreement_status(agreement):
	"""Derive the operational status of a submitted agreement from its lines."""
	doc = frappe.db.get_value(
		"Rental Agreement", agreement, ["docstatus", "status", "actual_end_date"], as_dict=True
	)
	if not doc or doc.docstatus != 1:
		return doc and doc.status

	lines = frappe.get_all(
		"Rental Agreement Item",
		filters={"parent": agreement, "parenttype": "Rental Agreement"},
		fields=["line_status", "return_datetime"],
	)
	live = [d for d in lines if d.line_status != CANCELLED]
	states = {d.line_status for d in live}

	if live and states == {RETURNED}:
		new_status = "Closed"
	elif ON_HIRE in states:
		new_status = "Partially Returned" if RETURNED in states else "Active"
	elif RETURNED in states:
		new_status = "Partially Returned"
	else:
		new_status = "Approved"

	values = {"status": new_status}
	if new_status == "Closed":
		values["actual_end_date"] = getdate(max(d.return_datetime for d in live))
		values["is_overdue"] = 0
	elif doc.actual_end_date:
		values["actual_end_date"] = None

	frappe.db.set_value("Rental Agreement", agreement, values)
	return new_status


def get_line(agreement, row_name):
	return frappe.db.get_value(
		"Rental Agreement Item",
		{"name": row_name, "parent": agreement, "parenttype": "Rental Agreement"},
		["name", "asset", "line_status", "dispatch_datetime", "return_datetime", "rental_item", "monthly_rate"],
		as_dict=True,
	)


NUMERIC_LINE_FIELDS = ("billable_days", "line_amount")


def set_line(row_name, **values):
	for field in NUMERIC_LINE_FIELDS:
		if field in values:
			values[field] = flt(values[field])
	frappe.db.set_value("Rental Agreement Item", row_name, values, update_modified=False)
