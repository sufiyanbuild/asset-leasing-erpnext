"""Sales Invoice validate handler - P1-09, P1-13.

The most important rule in P1. Sales Invoice Item.asset is a core ERPNext field
meaning "this invoice disposes of this asset" - populating it on a rental line
would mark the customer's equipment Sold. Rental equipment is identified by
al_asset instead, and the two must never both be set on one line.
"""

import frappe
from frappe import _


def validate(doc, method=None):
	rental_rows = [d for d in (doc.get("items") or []) if d.get("al_asset")]
	purpose = doc.get("al_invoice_purpose") or "Standard"

	# Early exit keeps this handler off every unrelated invoice on the site.
	if not rental_rows and purpose == "Standard":
		return

	for row in rental_rows:
		# VAL-P1-07
		if row.get("asset"):
			frappe.throw(
				_("Row #{0}: the core <b>Asset</b> field must be empty on a rental line."
				  "<br><br>That field marks an invoice as an asset <b>disposal</b> - "
				  "equipment {1} would be marked <i>Sold</i>. Use <b>Equipment</b> "
				  "({2}) to identify rented equipment.").format(row.idx, row.asset, row.al_asset),
				title=_("Rental Line Cannot Dispose of an Asset"),
			)

		asset = frappe.db.get_value("Asset", row.al_asset, ["al_is_rentable", "asset_name"], as_dict=True)
		if not asset:
			frappe.throw(_("Row #{0}: Asset {1} does not exist.").format(row.idx, row.al_asset))
		if not asset.al_is_rentable:
			frappe.throw(
				_("Row #{0}: Asset {1} is not marked <b>Available for Rental</b>.").format(row.idx, row.al_asset)
			)

	if purpose == "Rental" and not rental_rows:
		frappe.throw(
			_("Invoice Purpose is <b>Rental</b> but no line identifies any equipment. "
			  "Set <b>Equipment</b> on at least one line.")
		)
