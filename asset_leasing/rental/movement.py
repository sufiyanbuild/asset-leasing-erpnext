"""Standard Asset Movement documents for every physical move.

Custody history lives where ERPNext expects it. Rules carried from the
specification (Section 10.6) and the crm.local prototype:

* Purpose is always Transfer. Issue demands an Employee, because it models
  internal custody; a customer is not an employee.
* One movement per rental document, carrying every machine on it.
* Asset.location is never written here. The submitted movement moves it.
* A machine already at the target is left out; an empty movement is refused.
* Movements raised by this app carry a flag. The Asset Movement handler
  refuses to cancel them directly, so the rental document that raised them is
  always cancelled first and the two cannot drift apart.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime

RENTAL_REFERENCES = ("Rental Dispatch", "Rental Return", "Rental Agreement")
FLAG = "al_rental_movement"


def make_movement(company, reference_doctype, reference_name, moves, transaction_date):
	"""Create and submit one Transfer movement.

	moves is a list of (asset, target_location). Returns the movement name.
	"""
	rows = []
	for asset, target in moves:
		current = frappe.db.get_value("Asset", asset, "location")
		if current == target:
			continue
		rows.append({"asset": asset, "source_location": current, "target_location": target})

	if not rows:
		frappe.throw(
			_("Every machine on {0} is already at its destination, so there is nothing to move.").format(
				reference_name
			),
			title=_("No Movement Required"),
		)

	movement = frappe.get_doc({
		"doctype": "Asset Movement",
		"company": company,
		"purpose": "Transfer",
		"transaction_date": get_datetime(transaction_date),
		"reference_doctype": reference_doctype,
		"reference_name": reference_name,
		"assets": rows,
	})
	movement.flags.ignore_permissions = True
	movement.flags[FLAG] = True
	movement.insert()
	movement.submit()
	return movement.name


def cancel_movement(name):
	if not name:
		return
	movement = frappe.get_doc("Asset Movement", name)
	if movement.docstatus != 1:
		return
	movement.flags.ignore_permissions = True
	movement.flags[FLAG] = True
	movement.cancel()


def later_movements(asset, after, exclude=None):
	"""Submitted movements of this asset dated at or after the given moment."""
	rows = frappe.get_all(
		"Asset Movement",
		filters=[
			["Asset Movement Item", "asset", "=", asset],
			["docstatus", "=", 1],
			["transaction_date", ">=", get_datetime(after)],
		],
		fields=["name", "transaction_date", "reference_doctype", "reference_name"],
		order_by="transaction_date asc",
	)
	return [r for r in rows if r.name != exclude]
