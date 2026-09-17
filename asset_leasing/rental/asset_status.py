"""Operational rental status for an Asset.

Standard Asset.status is accounting and lifecycle state - Draft, Submitted,
Sold, Scrapped, In Maintenance. It has no way to say a machine is reserved for
a customer, on hire, or in transit, and overloading it would interfere with
depreciation and disposal behaviour. al_rental_status is a separate, parallel
field owned entirely by this module.

The field is read_only on the form. set_status() is the only writer, so the
transition rules below cannot be bypassed from the interface.

Callers: agreement approval and cancellation (Reserved / Available), dispatch
(On Hire), return (Under Inspection, then Available or Under Repair) and the
Asset Repair handlers (Under Repair / Available).
"""

import frappe
from frappe import _

AVAILABLE = "Available"
RESERVED = "Reserved"
ON_HIRE = "On Hire"
IN_TRANSIT = "In Transit"
UNDER_INSPECTION = "Under Inspection"
UNDER_REPAIR = "Under Repair"
RETIRED = "Retired"

ALL_STATUSES = [AVAILABLE, RESERVED, ON_HIRE, IN_TRANSIT, UNDER_INSPECTION, UNDER_REPAIR, RETIRED]

# States from which a machine is physically out of the yard. Used by guards that
# must refuse destructive changes while equipment is in the field.
OUT_OF_YARD = {RESERVED, ON_HIRE, IN_TRANSIT}

ALLOWED_TRANSITIONS = {
	AVAILABLE: {RESERVED, UNDER_REPAIR, UNDER_INSPECTION, RETIRED},
	RESERVED: {ON_HIRE, IN_TRANSIT, AVAILABLE},
	IN_TRANSIT: {ON_HIRE, AVAILABLE},
	ON_HIRE: {IN_TRANSIT, UNDER_INSPECTION, AVAILABLE},
	UNDER_INSPECTION: {AVAILABLE, UNDER_REPAIR},
	UNDER_REPAIR: {AVAILABLE, RETIRED},
	RETIRED: set(),  # terminal
}


def can_transition(from_status, to_status):
	if from_status == to_status:
		return True
	return to_status in ALLOWED_TRANSITIONS.get(from_status, set())


def assert_transition(from_status, to_status, asset=None):
	"""Raise unless the transition is legal, naming both states and the options."""
	if can_transition(from_status, to_status):
		return
	permitted = sorted(ALLOWED_TRANSITIONS.get(from_status, set())) or [_("none - this is a terminal state")]
	frappe.throw(
		_("{0}Cannot change rental status from <b>{1}</b> to <b>{2}</b>.<br><br>"
		  "Permitted from {1}: {3}").format(
			f"Asset {asset}: " if asset else "", from_status, to_status, ", ".join(permitted)
		),
		title=_("Invalid Rental Status Change"),
	)


def set_status(asset, new_status, reason=None, reversal_of=None):
	"""The only supported writer of al_rental_status.

	Validates the transition, writes the value, and records why on the Asset's
	timeline so the history of a machine is readable without trawling versions.

	reversal_of names a document being cancelled. Cancelling a dispatch or a
	return puts the machine back exactly where that document found it, which is
	an undo rather than a business transition, so the transition table is not
	consulted. The timeline still records it.
	"""
	if new_status not in ALL_STATUSES:
		frappe.throw(_("Unknown rental status {0}").format(new_status))

	current = frappe.db.get_value("Asset", asset, "al_rental_status") or AVAILABLE
	if current == new_status:
		return current

	if not reversal_of:
		assert_transition(current, new_status, asset=asset)
	frappe.db.set_value("Asset", asset, "al_rental_status", new_status, update_modified=False)

	note = _("Rental status: {0} &rarr; {1}").format(current, new_status)
	if reversal_of:
		note = f"{note}<br>{_('Restored because {0} was cancelled.').format(reversal_of)}"
	if reason:
		note = f"{note}<br>{reason}"
	frappe.get_doc("Asset", asset).add_comment("Info", note)
	return new_status


def get_status(asset):
	return frappe.db.get_value("Asset", asset, "al_rental_status") or AVAILABLE


def assert_not_out_of_yard(asset, action):
	"""Refuse a destructive change while the machine is not in our possession."""
	status = frappe.db.get_value("Asset", asset, "al_rental_status")
	if status in OUT_OF_YARD:
		frappe.throw(
			_("Asset {0} is <b>{1}</b> and cannot be {2} until it is back in the yard.").format(
				asset, status, action
			)
		)
