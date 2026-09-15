"""Customer validate handler - P1-08."""

import frappe
from frappe import _
from frappe.utils import flt


def validate(doc, method=None):
	# VAL-P1-08
	if doc.get("al_hire_blocked") and not (doc.get("al_hire_block_reason") or "").strip():
		frappe.throw(_("Record a <b>Reason for Block</b> when blocking a customer for hire."))

	if flt(doc.get("al_deposit_held")) < 0:
		frappe.throw(_("Security Deposit Held cannot be negative."))
