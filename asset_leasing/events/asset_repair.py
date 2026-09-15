"""Asset Repair validate handler - P1-11."""

import frappe
from frappe import _

from asset_leasing.rental.validators import assert_customer_not_blocked


def validate(doc, method=None):
	if not doc.get("al_chargeable_to_customer"):
		return

	# VAL-P1-09
	if not doc.get("al_customer"):
		frappe.throw(_("A chargeable repair needs a customer in <b>Chargeable To</b>."))

	assert_customer_not_blocked(doc.al_customer)
