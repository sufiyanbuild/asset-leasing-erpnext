"""Recompute which agreement holds each rentable machine.

P2 pointed an asset at the most recently approved agreement. The holder is now
derived from the agreements themselves (earliest approved booking still to be
dispatched), so existing records are brought into line once. Only the display
fields and the Reserved/Available half of the status are touched.
"""

import frappe

from asset_leasing.rental.lifecycle import refresh_asset_hold


def execute():
	for asset in frappe.get_all("Asset", filters={"al_is_rentable": 1, "docstatus": 1}, pluck="name"):
		refresh_asset_hold(asset)
