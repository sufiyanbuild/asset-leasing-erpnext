"""Rental Agreement - the hire contract.

Deliberately not a Sales Order: a Sales Order commits quantity for delivery,
whereas a hire commits a specific machine for a duration. Deliberately not the
standard Contract DocType either - Contract has no line items and cannot hold
assets, rates and periods.

Pricing is gated. monthly_rate is the one confirmed commercial figure (Q-01) and
is fetched from the Rental - Monthly price list. Everything derived from it -
daily rate, line amount, estimated value - stays blank until the client answers
Q-14 to Q-18. This class must never invent those numbers.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import date_diff, flt, getdate

from asset_leasing.rental import asset_status as st
from asset_leasing.rental.availability import assert_available
from asset_leasing.rental.validators import (
	assert_customer_not_blocked,
	assert_not_fixed_asset_item,
)

BLOCKING_LINE_STATUSES = ("On Hire",)


class RentalAgreement(Document):
	# ------------------------------------------------------------- validate
	def validate(self):
		self.validate_period()
		self.validate_customer()
		self.validate_hire_type()
		self.set_currency()
		self.validate_items()
		self.set_expected_days()
		self.sync_status()

	def validate_period(self):
		"""VAL-02 - a hire cannot end before it starts."""
		if self.is_open_ended:
			# An open-ended hire has no agreed end; any value would be misleading.
			self.expected_end_date = None
		elif not self.expected_end_date:
			frappe.throw(_("Set an <b>Expected End Date</b>, or tick <b>Open Ended</b>."))
		elif getdate(self.expected_end_date) < getdate(self.start_date):
			frappe.throw(
				_("Expected End Date ({0}) cannot be before the Start Date ({1}).").format(
					frappe.format(self.expected_end_date, "Date"),
					frappe.format(self.start_date, "Date"),
				)
			)

	def validate_customer(self):
		"""VAL-15 - a commercial block is independent of the credit limit.

		Credit-limit enforcement is intentionally absent: with pricing gated there
		is no agreement value to test an exposure against, and inventing one would
		be worse than omitting the check. It arrives with pricing.
		"""
		assert_customer_not_blocked(self.customer)

	def validate_hire_type(self):
		"""VAL-17 - wet hire supplies an operator with the machine."""
		if self.hire_type == "Wet Hire" and not self.operator:
			frappe.throw(_("A <b>Wet Hire</b> agreement must name an operator."))
		if self.hire_type == "Dry Hire":
			self.operator = None

	def set_currency(self):
		if self.currency:
			return
		self.currency = frappe.db.get_value("Customer", self.customer, "default_currency") or \
			frappe.db.get_value("Company", self.company, "default_currency")

	def validate_items(self):
		if not self.items:
			frappe.throw(_("Add at least one machine to the agreement."))

		seen = {}
		for row in self.items:
			self.validate_asset(row)

			# VAL-08 - the same machine twice on one agreement is always an error.
			if row.asset in seen:
				frappe.throw(
					_("Row #{0}: equipment <b>{1}</b> already appears on row #{2}.").format(
						row.idx, row.asset, seen[row.asset]
					)
				)
			seen[row.asset] = row.idx

			# VAL-06 - the machine must not already be promised to someone else.
			assert_available(
				row.asset,
				self.start_date,
				None if self.is_open_ended else self.expected_end_date,
				exclude_agreement=self.name,
				row_idx=row.idx,
			)

			self.set_rate(row)

	def validate_asset(self, row):
		asset = frappe.db.get_value(
			"Asset", row.asset,
			["docstatus", "status", "company", "al_is_rentable", "al_rental_item", "asset_name"],
			as_dict=True,
		)
		if not asset:
			frappe.throw(_("Row #{0}: Asset {1} does not exist.").format(row.idx, row.asset))

		# VAL-29
		if asset.docstatus != 1:
			frappe.throw(
				_("Row #{0}: Asset {1} is not submitted and cannot be hired out.").format(row.idx, row.asset)
			)
		if asset.status in ("Sold", "Scrapped", "Cancelled", "Capitalized"):
			frappe.throw(
				_("Row #{0}: Asset {1} is {2} and cannot be hired out.").format(
					row.idx, row.asset, asset.status
				)
			)
		# VAL-13
		if not asset.al_is_rentable:
			frappe.throw(
				_("Row #{0}: Asset {1} is not marked <b>Available for Rental</b>.").format(row.idx, row.asset)
			)
		# VAL-30
		if self.company and asset.company != self.company:
			frappe.throw(
				_("Row #{0}: Asset {1} belongs to company {2}, not {3}.").format(
					row.idx, row.asset, asset.company, self.company
				)
			)

		if not row.rental_item:
			row.rental_item = asset.al_rental_item
		if not row.rental_item:
			frappe.throw(
				_("Row #{0}: Asset {1} has no Rental Charge Item.").format(row.idx, row.asset)
			)

		# VAL-26 - billing rent with a fixed-asset item would post a disposal.
		assert_not_fixed_asset_item(row.rental_item, _("Rental Charge Item"))

	def set_rate(self, row):
		"""Fetch the one confirmed rate. Derive nothing from it."""
		if flt(row.monthly_rate):
			return
		from asset_leasing.rental.pricing import get_monthly_rate

		try:
			row.monthly_rate = get_monthly_rate(row.rental_item, customer=self.customer)
		except frappe.ValidationError:
			# No price on the monthly list yet. Not fatal at agreement stage -
			# the rate can be typed in - but flag it rather than silently zero.
			frappe.msgprint(
				_("Row #{0}: no monthly price found for {1}. Enter the rate manually.").format(
					row.idx, row.rental_item
				),
				indicator="orange", alert=True,
			)

	def set_expected_days(self):
		"""Calendar span only. This is NOT a billing figure - see Q-14 to Q-18."""
		for row in self.items:
			if self.is_open_ended or not self.expected_end_date:
				row.expected_days = 0
			else:
				row.expected_days = date_diff(self.expected_end_date, self.start_date) + 1

	def sync_status(self):
		if self.docstatus == 0:
			self.status = "Cancelled" if self.status == "Cancelled" else "Draft"

	# -------------------------------------------------------------- submit
	def on_submit(self):
		self.db_set("status", "Approved")
		self.reserve_assets()

	def reserve_assets(self):
		"""Hold each machine for this customer so nobody else can commit it."""
		for row in self.items:
			st.set_status(
				row.asset, st.RESERVED,
				reason=_("Reserved for {0} on agreement {1}.").format(self.customer, self.name),
			)
			frappe.db.set_value(
				"Asset", row.asset,
				{"al_current_agreement": self.name, "al_current_customer": self.customer},
				update_modified=False,
			)

	# -------------------------------------------------------------- cancel
	def on_cancel(self):
		self.validate_no_equipment_in_field()
		self.release_assets()
		self.db_set("status", "Cancelled")

	def validate_no_equipment_in_field(self):
		"""VAL-22 - equipment must come back before the paperwork disappears."""
		out = [r.asset for r in self.items if r.line_status in BLOCKING_LINE_STATUSES]
		if out:
			frappe.throw(
				_("Cannot cancel: equipment is still on hire &mdash; {0}. Record the return first.").format(
					", ".join(out)
				),
				title=_("Equipment Still In The Field"),
			)

	def release_assets(self):
		for row in self.items:
			current = frappe.db.get_value("Asset", row.asset, "al_current_agreement")
			if current != self.name:
				continue
			frappe.db.set_value(
				"Asset", row.asset,
				{"al_current_agreement": None, "al_current_customer": None},
				update_modified=False,
			)
			if frappe.db.get_value("Asset", row.asset, "al_rental_status") == st.RESERVED:
				st.set_status(
					row.asset, st.AVAILABLE,
					reason=_("Released - agreement {0} cancelled.").format(self.name),
				)
