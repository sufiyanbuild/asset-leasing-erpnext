"""Sales Invoice handlers - P1-09, P1-13, VAL-05, VAL-27 and the billing roll-ups.

The most important rule here. Sales Invoice Item.asset is a core ERPNext field
meaning "this invoice disposes of this asset" - populating it on a rental line
would mark the customer's equipment Sold. Rental equipment is identified by
al_asset instead, and the two must never both be set on one line.
"""

import frappe
from frappe import _
from frappe.utils import getdate

from asset_leasing.rental import billing


def validate(doc, method=None):
	billing.stamp_subscription_invoice(doc)

	rental_rows = [d for d in (doc.get("items") or []) if d.get("al_asset")]
	purpose = doc.get("al_invoice_purpose") or "Standard"

	# Early exit keeps this handler off every unrelated invoice on the site.
	if not rental_rows and purpose == "Standard" and not doc.get("al_rental_agreement"):
		return

	for row in rental_rows:
		# VAL-P1-07 / VAL-27
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

	if doc.get("al_rental_agreement"):
		validate_against_agreement(doc)


def validate_against_agreement(doc):
	agreement = frappe.db.get_value(
		"Rental Agreement", doc.al_rental_agreement,
		["customer", "company", "start_date", "expected_end_date", "actual_end_date", "docstatus"],
		as_dict=True,
	)
	if not agreement:
		return
	if agreement.customer != doc.customer:
		frappe.throw(
			_("Invoice customer {0} does not match {1} on agreement {2}.").format(
				doc.customer, agreement.customer, doc.al_rental_agreement
			)
		)
	if agreement.docstatus == 2 and doc.docstatus < 2:
		frappe.throw(_("Agreement {0} is cancelled and cannot be billed.").format(doc.al_rental_agreement))

	# VAL-05 - never bill for time outside the contract.
	if doc.get("from_date") and doc.get("to_date"):
		start, end = getdate(doc.from_date), getdate(doc.to_date)
		if start > end:
			frappe.throw(_("Billing period From Date {0} is after To Date {1}.").format(
				frappe.format(start, "Date"), frappe.format(end, "Date")))
		if start < getdate(agreement.start_date):
			frappe.throw(_("Billing period starts {0}, before agreement {1} begins ({2}).").format(
				frappe.format(start, "Date"), doc.al_rental_agreement, frappe.format(agreement.start_date, "Date")))
		last = agreement.actual_end_date or agreement.expected_end_date
		if last and end > getdate(last):
			frappe.throw(_("Billing period ends {0}, after agreement {1} ends ({2}).").format(
				frappe.format(end, "Date"), doc.al_rental_agreement, frappe.format(last, "Date")))


def on_submit(doc, method=None):
	_roll_up(doc)


def on_cancel(doc, method=None):
	_roll_up(doc)


def _roll_up(doc):
	if not doc.get("al_rental_agreement"):
		return
	billing.update_agreement_billed(doc.al_rental_agreement)
	billing.update_asset_revenue([d.al_asset for d in doc.items if d.get("al_asset")])
