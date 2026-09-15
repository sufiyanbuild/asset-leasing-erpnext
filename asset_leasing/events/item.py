"""Item validate handler - P1-02."""

import frappe
from frappe import _


def validate(doc, method=None):
	if not doc.get("al_is_rental_item"):
		return

	# VAL-P1-06 - mutually exclusive by definition.
	if doc.get("is_fixed_asset"):
		frappe.throw(
			_("An item cannot be both <b>Is Fixed Asset</b> and <b>Is Rental Charge Item</b>."
			  "<br><br>ERPNext books a fixed-asset item on a Sales Invoice as an asset "
			  "<b>disposal</b>. A rental charge item must be a non-stock service item."),
			title=_("Conflicting Item Configuration"),
		)

	if doc.get("is_stock_item"):
		frappe.msgprint(
			_("Rental charge items are normally non-stock service items."),
			indicator="orange", alert=True,
		)
