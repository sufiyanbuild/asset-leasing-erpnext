"""Asset validate handler - P1-01, P1-02, P1-04."""

import frappe
from frappe import _

from asset_leasing.rental.asset_status import AVAILABLE, OUT_OF_YARD, RETIRED, assert_transition
from asset_leasing.rental.compliance import compliance_status
from asset_leasing.rental.validators import assert_not_fixed_asset_item, assert_yard_location


def validate(doc, method=None):
	_guard_status_change(doc)
	doc.al_compliance_status = compliance_status(doc)

	if not doc.get("al_is_rentable"):
		_guard_withdrawal(doc)
		return

	# VAL-P1-01 - a rentable asset must be billable and have somewhere to come back to.
	if not doc.get("al_rental_item"):
		frappe.throw(_("A rentable asset needs a <b>Rental Charge Item</b> - the service item used to bill its rent."))
	if not doc.get("al_base_location"):
		frappe.throw(_("A rentable asset needs a <b>Home / Yard Location</b> - where it returns to when off hire."))

	# VAL-P1-02 - the trap that would mark the machine Sold on its first invoice.
	assert_not_fixed_asset_item(doc.al_rental_item, _("Rental Charge Item"))

	# VAL-P1-05 - advisory while Q-23 is open.
	assert_yard_location(doc.al_base_location, _("Home / Yard Location"))

	if not doc.get("al_rental_status"):
		doc.al_rental_status = AVAILABLE


def _guard_status_change(doc):
	"""VAL-P1-03 - al_rental_status is owned by asset_status.set_status().

	The field is read_only on the form, but read_only is a UI hint that the API
	does not enforce, so the rule lives here. set_status() writes through
	frappe.db.set_value, which does not run validate, so a legitimate dispatch
	or return never reaches this guard.
	"""
	if doc.is_new():
		return

	previous = frappe.db.get_value("Asset", doc.name, "al_rental_status")
	current = doc.get("al_rental_status")
	if previous == current:
		return

	# Populating a blank on an existing record is a migration artefact, not a change.
	if not previous and current == AVAILABLE:
		return

	assert_transition(previous or AVAILABLE, current, asset=doc.name)
	frappe.throw(
		_("Rental Status is maintained by dispatch and return, not by editing the Asset.<br><br>"
		  "Asset {0} is currently <b>{1}</b>.").format(doc.name, previous),
		title=_("Rental Status Is Read-Only"),
	)


def _guard_withdrawal(doc):
	"""VAL-P1-04 - a machine in the field cannot be removed from the fleet."""
	if doc.is_new():
		return
	was_rentable = frappe.db.get_value("Asset", doc.name, "al_is_rentable")
	if not was_rentable:
		return
	status = frappe.db.get_value("Asset", doc.name, "al_rental_status")
	if status in OUT_OF_YARD:
		frappe.throw(
			_("Asset {0} is <b>{1}</b> and cannot be marked not-for-rental until it is back in the yard.").format(
				doc.name, status
			)
		)
