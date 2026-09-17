"""Asset Repair handlers - P1-11 and the repair side of the rental status (AL-21).

A machine in the yard is Under Repair while it has an open repair job, and
returns to Available when the last one is closed. A machine on hire keeps its
status: a repair carried out on site does not end the hire.
"""

import frappe
from frappe import _

from asset_leasing.rental import asset_status as st
from asset_leasing.rental import lifecycle
from asset_leasing.rental.validators import assert_customer_not_blocked


def validate(doc, method=None):
	if not doc.get("al_chargeable_to_customer"):
		return

	# VAL-P1-09
	if not doc.get("al_customer"):
		frappe.throw(_("A chargeable repair needs a customer in <b>Chargeable To</b>."))

	assert_customer_not_blocked(doc.al_customer)


def _is_rentable(asset):
	return frappe.db.get_value("Asset", asset, "al_is_rentable")


def on_update(doc, method=None):
	"""An open repair takes a machine in the yard out of service."""
	if doc.docstatus != 0 or doc.repair_status != "Pending" or not _is_rentable(doc.asset):
		return
	if st.get_status(doc.asset) == st.AVAILABLE:
		st.set_status(doc.asset, st.UNDER_REPAIR, reason=_("Repair {0} opened.").format(doc.name))


def on_submit(doc, method=None):
	_release_if_last(doc, _("Repair {0} {1}.").format(doc.name, (doc.repair_status or "").lower()))


def after_delete(doc, method=None):
	if doc.docstatus == 0:
		_release_if_last(doc, _("Repair {0} deleted.").format(doc.name))


def _release_if_last(doc, reason):
	if not _is_rentable(doc.asset) or st.get_status(doc.asset) != st.UNDER_REPAIR:
		return
	still_open = frappe.get_all(
		"Asset Repair",
		filters={"asset": doc.asset, "docstatus": 0, "repair_status": "Pending", "name": ["!=", doc.name]},
		pluck="name",
	)
	if still_open:
		return
	st.set_status(doc.asset, st.AVAILABLE, reason=reason)
	lifecycle.refresh_asset_hold(doc.asset)
