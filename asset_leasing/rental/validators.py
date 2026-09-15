"""Reusable business predicates shared by the document event handlers.

Kept separate from the handlers so the same rule cannot drift between the two
places that need it, and so each is unit-testable without building a document.
"""

import frappe
from frappe import _


def assert_not_fixed_asset_item(item_code, fieldlabel=None):
	"""A rental charge item must never be a fixed-asset item.

	An Asset's own item_code is always a fixed-asset item (asset.py validates
	this). ERPNext books a fixed-asset item on a Sales Invoice as an asset
	DISPOSAL - the machine would be marked Sold on its first rent invoice. The
	rent must therefore be billed through a separate non-stock service item.
	"""
	if not item_code:
		return

	item = frappe.db.get_value("Item", item_code, ["is_fixed_asset", "is_stock_item", "disabled"], as_dict=True)
	if not item:
		frappe.throw(_("Item {0} does not exist.").format(item_code))

	if item.disabled:
		frappe.throw(_("Item {0} is disabled and cannot be used to bill rent.").format(item_code))

	if item.is_fixed_asset:
		frappe.throw(
			_("{0} <b>{1}</b> is a Fixed Asset item and cannot be used to bill rent."
			  "<br><br>ERPNext books a fixed-asset item on a Sales Invoice as an asset "
			  "<b>disposal</b> - the equipment would be marked <i>Sold</i> on its first "
			  "rent invoice.<br><br>Use a non-stock service item instead, for example "
			  "'Excavator Rental - Monthly'.").format(fieldlabel or _("Item"), item_code),
			title=_("Fixed Asset Item Cannot Bill Rent"),
		)

	if item.is_stock_item:
		frappe.msgprint(
			_("Item {0} is a stock item. Rental charge items are normally non-stock services.").format(item_code),
			indicator="orange", alert=True,
		)


def assert_customer_not_blocked(customer):
	if not customer:
		return
	blocked, reason = frappe.db.get_value("Customer", customer, ["al_hire_blocked", "al_hire_block_reason"]) or (0, None)
	if blocked:
		frappe.throw(
			_("Customer {0} is blocked for hire.<br><br>{1}").format(customer, reason or _("No reason recorded.")),
			title=_("Customer Blocked for Hire"),
		)


def assert_rentable(asset):
	"""The asset exists, is submitted, and is marked available for rental."""
	if not asset:
		return
	row = frappe.db.get_value(
		"Asset", asset, ["docstatus", "status", "al_is_rentable", "asset_name"], as_dict=True
	)
	if not row:
		frappe.throw(_("Asset {0} does not exist.").format(asset))
	if row.docstatus != 1:
		frappe.throw(_("Asset {0} is not submitted and cannot be rented out.").format(asset))
	if not row.al_is_rentable:
		frappe.throw(_("Asset {0} is not marked <b>Available for Rental</b>.").format(asset))
	if row.status in ("Sold", "Scrapped", "Cancelled", "Capitalized"):
		frappe.throw(_("Asset {0} is {1} and cannot be rented out.").format(asset, row.status))


def assert_yard_location(location, fieldlabel=None):
	"""A home location should be one of our own yards.

	Warns rather than throws while Q-23 is open: until the client confirms
	whether third-party and in-transit locations are real, a hard block could
	stop legitimate data entry.
	"""
	if not location:
		return
	loc_type = frappe.db.get_value("Location", location, "al_location_type")
	if loc_type and loc_type != "Owned Yard":
		frappe.msgprint(
			_("{0} <b>{1}</b> is classified as <b>{2}</b>, not an Owned Yard.").format(
				fieldlabel or _("Location"), location, loc_type
			),
			indicator="orange", alert=True,
		)
