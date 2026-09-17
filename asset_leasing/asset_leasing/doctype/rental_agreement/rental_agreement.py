"""Rental Agreement - the hire contract.

Deliberately not a Sales Order: a Sales Order commits quantity for delivery,
whereas a hire commits a specific machine for a duration. Deliberately not the
standard Contract DocType either - Contract has no line items and cannot hold
assets, rates and periods.

Two independent state fields:

* workflow_state - the approval decision (Rental Agreement Approval workflow).
  Approve is the submit.
* status - what has physically happened: Approved, Active, Partially
  Returned, Closed, Cancelled. Driven by dispatch and return documents through
  rental/lifecycle.py, never by a workflow action.

monthly_rate is the one commercial figure (Q-01). A Short Term Hire derives its
daily rate and estimated value from it under the confirmed pro-rata policy
(Q-14 to Q-18, rental/pricing.py); the rent actually billed is computed at
return from the real dispatch and return times. A Long Term Contract bills
whole monthly periods through a Subscription, so its value needs no proration.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import date_diff, flt, get_datetime, getdate, now_datetime

from asset_leasing.rental import asset_status as st
from asset_leasing.rental import billing, lifecycle, pricing
from asset_leasing.rental.availability import assert_available
from asset_leasing.rental.credit import assert_within_credit_limit
from asset_leasing.rental.movement import make_movement
from asset_leasing.rental.validators import (
	assert_customer_not_blocked,
	assert_not_fixed_asset_item,
)

BLOCKING_LINE_STATUSES = ("On Hire",)
LONG_TERM = billing.LONG_TERM


class RentalAgreement(Document):
	# ------------------------------------------------------------- validate
	def validate(self):
		self.validate_period()
		self.validate_customer()
		self.validate_hire_type()
		self.set_currency()
		self.validate_items()
		self.set_expected_days()
		self.set_estimated_value()
		self.sync_status()

	def validate_period(self):
		"""VAL-02 - a hire cannot end before it starts."""
		if self.is_open_ended and self.agreement_type == LONG_TERM:
			frappe.throw(
				_("A Long Term Contract runs for a fixed term. <b>Open Ended</b> applies to Short Term Hire only."),
				title=_("Fixed Term Required"),
			)
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
		if self.agreement_type == LONG_TERM and self.expected_end_date:
			billing.assert_whole_month_term(self.start_date, self.expected_end_date)

	def validate_customer(self):
		"""VAL-15 - a commercial block, then the credit limit already in use.

		Approval (before_submit) repeats the credit check with this agreement's
		estimated value added.
		"""
		assert_customer_not_blocked(self.customer)
		assert_within_credit_limit(self.customer, self.company, _("a new hire"))

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
		if not row.asset:
			frappe.throw(_("Row #{0}: choose the equipment, or remove the empty row.").format(row.idx))
		asset = frappe.db.get_value(
			"Asset", row.asset,
			["docstatus", "status", "company", "al_is_rentable", "al_rental_item", "al_rental_status", "asset_name"],
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
		if not asset.al_is_rentable:
			frappe.throw(
				_("Row #{0}: Asset {1} is not marked <b>Available for Rental</b>.").format(row.idx, row.asset)
			)
		if asset.al_rental_status == st.RETIRED and self.docstatus == 0:
			frappe.throw(_("Row #{0}: Asset {1} is retired from the hire fleet.").format(row.idx, row.asset))
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
		if flt(row.monthly_rate) or row.is_free_of_charge:
			return
		from asset_leasing.rental.pricing import get_monthly_rate

		try:
			row.monthly_rate = get_monthly_rate(row.rental_item, customer=self.customer, company=self.company)
		except frappe.ValidationError:
			# VAL-28 - not fatal on a draft (the rate can be typed in), but flagged
			# rather than silently zero. Approval refuses a zero rate.
			from frappe.utils.messages import clear_last_message

			clear_last_message()
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

	def set_estimated_value(self):
		"""The agreed period at the agreed rates. Open-ended hires have no estimate."""
		ready = pricing.policy_ready()
		for row in self.items:
			row.derived_daily_rate = (
				flt(pricing.derive_daily_rate(row.monthly_rate, self.start_date), 2) if ready else None
			)

		if not self.expected_end_date:
			self.estimated_rental_value = None
		elif self.agreement_type == LONG_TERM:
			self.estimated_rental_value = billing.contract_value(self)
		elif ready:
			self.estimated_rental_value = sum(
				pricing.estimate_period_amount(row.monthly_rate, self.start_date, self.expected_end_date).amount
				for row in self.items if not row.is_free_of_charge
			)
		else:
			self.estimated_rental_value = None

	def sync_status(self):
		if self.docstatus == 0:
			self.status = "Cancelled" if self.status == "Cancelled" else "Draft"

	# -------------------------------------------------------------- submit
	def before_submit(self):
		"""VAL-17 - an approved hire carries a price unless it is explicitly free."""
		for row in self.items:
			if flt(row.monthly_rate) <= 0 and not row.is_free_of_charge:
				frappe.throw(
					_("Row #{0}: {1} has no monthly rate. Enter the rate, or tick <b>Free of Charge</b> "
					  "for a replacement machine.").format(row.idx, row.asset),
					title=_("Rate Required"),
				)
			if flt(row.monthly_rate) < 0:
				frappe.throw(_("Row #{0}: the monthly rate cannot be negative.").format(row.idx))
		assert_within_credit_limit(
			self.customer, self.company, _("approving this agreement"),
			additional_exposure=flt(self.estimated_rental_value),
		)

	def on_submit(self):
		self.db_set("status", "Approved")
		for row in self.items:
			lifecycle.refresh_asset_hold(row.asset)
		if self.agreement_type == LONG_TERM:
			billing.create_subscription(self)

	# -------------------------------------------------------------- cancel
	def before_cancel(self):
		self.validate_no_equipment_in_field()

	def on_cancel(self):
		self.db_set("status", "Cancelled")
		self.release_assets()
		deleted = billing.cancel_subscription(self)
		if deleted:
			self.add_comment("Info", _("Draft subscription invoices removed: {0}").format(", ".join(deleted)))

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
		handled = frappe.get_all(
			"Rental Dispatch", filters={"rental_agreement": self.name, "docstatus": 1}, pluck="name"
		)
		if handled:
			frappe.throw(
				_("Cannot cancel: equipment has already been dispatched under this agreement ({0}). "
				  "A hire that has taken place is closed by its final return, not cancelled.").format(
					", ".join(handled)
				),
				title=_("Hire Already Under Way"),
			)

	def release_assets(self):
		for row in self.items:
			lifecycle.refresh_asset_hold(
				row.asset, reason=_("Released - agreement {0} cancelled.").format(self.name)
			)


# ------------------------------------------------------------------ actions
@frappe.whitelist()
def make_rental_agreement(source_name, target_doc=None):
	"""Quotation -> Rental Agreement (AL-06).

	Customer, company, site and expected duration are carried over. A quotation
	prices a kind of machine, not a specific unit, so each quoted rental item
	becomes a line to be completed by picking the actual machine.
	"""
	from frappe.model.mapper import get_mapped_doc
	from frappe.utils import add_days, nowdate

	quotation = frappe.get_doc("Quotation", source_name)
	quotation.check_permission("read")
	if quotation.docstatus != 1:
		frappe.throw(_("Only a submitted quotation can become a Rental Agreement."))
	if quotation.quotation_to != "Customer":
		frappe.throw(_("Convert the lead on {0} to a customer first.").format(source_name))

	def set_missing(source, target):
		target.agreement_type = billing.SHORT_TERM
		target.start_date = target.start_date or nowdate()
		days = source.get("al_expected_hire_days")
		if days:
			target.expected_end_date = add_days(target.start_date, int(days) - 1)
		target.items = []
		for row in source.items:
			if not frappe.db.get_value("Item", row.item_code, "al_is_rental_item"):
				continue
			for _unit in range(max(1, int(flt(row.qty)))):
				target.append("items", {"rental_item": row.item_code, "monthly_rate": row.rate})

	return get_mapped_doc(
		"Quotation", source_name,
		{
			"Quotation": {
				"doctype": "Rental Agreement",
				"field_map": {
					"party_name": "customer",
					"al_site_location": "site_location",
					"name": "quotation",
					"customer_address": "customer_address",
					"contact_person": "contact_person",
					"terms": "terms",
				},
				"field_no_map": ["status", "naming_series", "items"],
			},
		},
		target_doc,
		set_missing,
	)


@frappe.whitelist()
def transfer_equipment(agreement, asset, target_location, transfer_datetime=None, remarks=None):
	"""Move a machine on hire from one customer site to another (AL-19).

	The machine stays On Hire under the same agreement; a standard Asset
	Movement records the move, so the custody trail is complete.
	"""
	frappe.has_permission("Rental Dispatch", "create", throw=True)
	doc = frappe.get_doc("Rental Agreement", agreement)
	doc.check_permission("read")

	line = next((r for r in doc.items if r.asset == asset and r.line_status == lifecycle.ON_HIRE), None)
	if not line:
		frappe.throw(_("{0} is not on hire under {1}.").format(asset, agreement))

	moment = get_datetime(transfer_datetime) if transfer_datetime else now_datetime()
	if moment > now_datetime():
		frappe.throw(_("A transfer cannot be recorded in the future."))
	if moment <= get_datetime(line.dispatch_datetime):
		frappe.throw(_("The transfer must be after the dispatch of {0}.").format(asset))

	location = frappe.db.get_value("Location", target_location, ["is_group", "al_location_type"], as_dict=True)
	if not location:
		frappe.throw(_("Location {0} does not exist.").format(target_location))
	if location.is_group:
		frappe.throw(_("{0} is a location group. Choose the actual site.").format(target_location))
	if location.al_location_type == "Owned Yard":
		frappe.throw(_("{0} is one of our yards. Bring equipment back with a Rental Return.").format(target_location))

	current = frappe.db.get_value("Asset", asset, "location")
	if current == target_location:
		frappe.throw(_("{0} is already at {1}.").format(asset, target_location))

	movement = make_movement(doc.company, doc.doctype, doc.name, [(asset, target_location)], moment)
	note = _("{0} moved from {1} to {2} ({3}).").format(asset, current, target_location, movement)
	if remarks:
		note = f"{note}<br>{frappe.utils.escape_html(remarks)}"
	doc.add_comment("Info", note)
	frappe.get_doc("Asset", asset).add_comment("Info", note)
	return movement


@frappe.whitelist()
def get_billing_summary(agreement):
	"""Figures for the agreement's dashboard. Read-only."""
	doc = frappe.get_doc("Rental Agreement", agreement)
	doc.check_permission("read")
	from asset_leasing.rental import deposits, pricing

	invoices = frappe.get_all(
		"Sales Invoice",
		filters={"al_rental_agreement": agreement, "docstatus": ["<", 2]},
		fields=["name", "docstatus", "al_invoice_purpose", "grand_total", "outstanding_amount"],
	)
	summary = {
		"pricing_pending": pricing.pending_policy_questions() if doc.agreement_type != LONG_TERM else [],
		"draft_invoices": [i.name for i in invoices if i.docstatus == 0],
		"outstanding": sum(flt(i.outstanding_amount) for i in invoices if i.docstatus == 1),
		"transport": {
			"mobilisation": bool(flt(doc.mobilisation_charge)) and bool(billing.open_invoices({
				"al_rental_agreement": agreement, "al_invoice_purpose": billing.PURPOSE_TRANSPORT,
				"al_rental_dispatch": ["is", "set"]})),
			"demobilisation": bool(flt(doc.demobilisation_charge)) and bool(billing.open_invoices({
				"al_rental_agreement": agreement, "al_invoice_purpose": billing.PURPOSE_TRANSPORT,
				"al_rental_return": ["is", "set"]})),
		},
	}
	if doc.has_permlevel_access_to("deposit_held"):
		totals = deposits.agreement_deposit_totals(doc.name)
		summary["deposit_received"] = totals.received
		summary["deposit_refundable"] = (
			deposits.refundable_amount(doc.name, doc.customer, doc.company) if totals.held > 0 else 0
		)
	return summary
