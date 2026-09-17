"""Asset Movement handlers - keep the custody ledger and rental state in step.

Movements raised by a Rental Dispatch or Rental Return are cancelled through
that document, never directly. A machine that is on hire is moved only by the
rental documents or the site-transfer action, so its location and its rental
status cannot drift apart.
"""

import frappe
from frappe import _

from asset_leasing.rental import asset_status as st
from asset_leasing.rental.movement import FLAG, later_movements

GUARDED_STATUSES = (st.ON_HIRE, st.IN_TRANSIT)


def validate(doc, method=None):
	if doc.flags.get(FLAG):
		return
	for row in doc.assets:
		rentable, status = frappe.db.get_value("Asset", row.asset, ["al_is_rentable", "al_rental_status"]) or (0, None)
		if rentable and status in GUARDED_STATUSES:
			frappe.throw(
				_("Row #{0}: {1} is {2}. Move hired equipment with a Rental Return, or with "
				  "<b>Transfer to Another Site</b> on its Rental Agreement.").format(row.idx, row.asset, status),
				title=_("Equipment On Hire"),
			)


def before_cancel(doc, method=None):
	if doc.flags.get(FLAG):
		return
	if doc.reference_doctype in ("Rental Dispatch", "Rental Return"):
		frappe.throw(
			_("This movement was created by {0} {1}. Cancel that document instead.").format(
				_(doc.reference_doctype), doc.reference_name
			),
			title=_("Cancel the Rental Document"),
		)
	if doc.reference_doctype == "Rental Agreement":
		# A site-to-site transfer: allowed only while it is the latest move of a machine still on hire.
		for row in doc.assets:
			if st.get_status(row.asset) != st.ON_HIRE:
				frappe.throw(_("{0} is no longer on hire; this transfer cannot be reversed.").format(row.asset))
			if later_movements(row.asset, doc.transaction_date, exclude=doc.name):
				frappe.throw(_("{0} has moved again since this transfer. Reverse the later movement first.").format(
					row.asset))
