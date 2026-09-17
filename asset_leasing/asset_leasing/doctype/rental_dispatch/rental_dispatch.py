"""Rental Dispatch - equipment leaves the yard (AL-11).

On submit: one standard Asset Movement (Transfer) carries every machine to the
customer site, each machine goes On Hire, its agreement line records the
dispatch moment (the start of the billing clock), and the agreement becomes
Active. Cancelling reverses all of that, provided nothing has happened since.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_datetime, getdate, now_datetime

from asset_leasing.rental import asset_status as st
from asset_leasing.rental import billing, lifecycle
from asset_leasing.rental.compliance import assert_dispatchable
from asset_leasing.rental.credit import assert_within_credit_limit
from asset_leasing.rental.movement import cancel_movement, later_movements, make_movement

DISPATCHABLE_AGREEMENT_STATUSES = ("Approved", "Active", "Partially Returned")


class RentalDispatch(Document):
	def validate(self):
		self.agreement = self.get_agreement()
		self.set_party_from_agreement()
		self.validate_agreement()
		self.validate_datetime()
		self.validate_route()
		self.validate_transport()
		self.validate_items()
		if self.docstatus == 0:
			self.status = "Draft"

	def before_submit(self):
		# VAL-15 is re-checked at the moment equipment actually leaves.
		assert_within_credit_limit(self.customer, self.company, _("dispatch"))
		for row in self.items:
			assert_dispatchable(row.asset, getdate(self.dispatch_datetime), row_idx=row.idx)

	def get_agreement(self):
		return frappe.get_doc("Rental Agreement", self.rental_agreement)

	def set_party_from_agreement(self):
		"""VAL-11 - fetched fields are only a UI convenience; the API can set anything."""
		self.customer = self.agreement.customer
		self.customer_name = self.agreement.customer_name
		self.company = self.agreement.company
		self.to_location = self.agreement.site_location

	def validate_agreement(self):
		"""VAL-13 - only an approved agreement can release equipment."""
		if self.agreement.docstatus != 1 or self.agreement.status not in DISPATCHABLE_AGREEMENT_STATUSES:
			frappe.throw(
				_("Agreement {0} is {1}. Equipment can only be dispatched against an approved agreement.").format(
					self.agreement.name, self.agreement.status
				),
				title=_("Agreement Not Approved"),
			)

	def validate_datetime(self):
		"""VAL-03 - not before the hire starts, not in the future, not after it ends."""
		moment = get_datetime(self.dispatch_datetime)
		if moment > now_datetime():
			frappe.throw(_("Dispatch time {0} is in the future.").format(frappe.format(moment, "Datetime")))
		if getdate(moment) < getdate(self.agreement.start_date):
			frappe.throw(
				_("Dispatch date {0} is before the agreement start date {1}.").format(
					frappe.format(getdate(moment), "Date"), frappe.format(self.agreement.start_date, "Date")
				)
			)
		if self.agreement.expected_end_date and getdate(moment) > getdate(self.agreement.expected_end_date):
			frappe.throw(
				_("Dispatch date {0} is after the agreement's expected end date {1}. Extend the agreement first.").format(
					frappe.format(getdate(moment), "Date"), frappe.format(self.agreement.expected_end_date, "Date")
				)
			)

	def validate_route(self):
		"""VAL-14 - a real move, from a yard, to the agreed site."""
		if not self.to_location:
			frappe.throw(_("Agreement {0} has no site location.").format(self.agreement.name))
		if self.from_location == self.to_location:
			frappe.throw(_("From Yard and To Site cannot be the same location."))
		if frappe.db.get_value("Location", self.from_location, "is_group"):
			frappe.throw(_("{0} is a location group. Choose the actual yard.").format(self.from_location))

	def validate_transport(self):
		if self.transport_mode in ("Own Vehicle", "Hired Transport"):
			missing = [label for field, label in (("vehicle_no", _("Vehicle No")), ("driver_name", _("Driver Name")))
					   if not (self.get(field) or "").strip()]
			if missing:
				frappe.throw(_("{0} is required when transport is {1}.").format(", ".join(missing), self.transport_mode))

	def validate_items(self):
		lines = {row.name: row for row in self.agreement.items}
		seen = set()
		for row in self.items:
			line = self.resolve_line(row, lines)

			if row.asset in seen:
				frappe.throw(_("Row #{0}: equipment {1} appears twice.").format(row.idx, row.asset))
			seen.add(row.asset)

			# VAL-12 - matched by row, not by asset alone.
			if line.line_status != lifecycle.PENDING:
				frappe.throw(
					_("Row #{0}: {1} on agreement {2} is already {3}.").format(
						row.idx, row.asset, self.agreement.name, line.line_status
					)
				)

			self.validate_asset_state(row)

			if flt(row.meter_reading_out) < 0:
				frappe.throw(_("Row #{0}: meter reading cannot be negative.").format(row.idx))
			last = frappe.db.get_value("Asset", row.asset, "al_last_meter_reading")
			if row.meter_reading_out and last and flt(row.meter_reading_out) < flt(last):
				frappe.throw(
					_("Row #{0}: meter reading out {1} is below the last recorded reading {2} for {3}.").format(
						row.idx, row.meter_reading_out, last, row.asset
					),
					title=_("Meter Reading Went Backwards"),
				)

	def resolve_line(self, row, lines):
		if row.agreement_item:
			line = lines.get(row.agreement_item)
			if not line or line.asset != row.asset:
				frappe.throw(
					_("Row #{0}: {1} is not the machine on that line of agreement {2}.").format(
						row.idx, row.asset, self.agreement.name
					)
				)
			return line
		matches = [l for l in lines.values() if l.asset == row.asset and l.line_status == lifecycle.PENDING]
		if not matches:
			frappe.throw(
				_("Row #{0}: {1} is not waiting for dispatch on agreement {2}.").format(
					row.idx, row.asset, self.agreement.name
				)
			)
		row.agreement_item = matches[0].name
		return matches[0]

	def validate_asset_state(self, row):
		"""VAL-07 - the machine must be in the yard and free."""
		asset = frappe.db.get_value(
			"Asset", row.asset,
			["docstatus", "status", "company", "location", "al_rental_status", "al_current_customer"],
			as_dict=True,
		)
		if asset.docstatus != 1 or asset.status in ("Sold", "Scrapped", "Cancelled", "Capitalized"):
			frappe.throw(_("Row #{0}: asset {1} is {2} and cannot be dispatched.").format(row.idx, row.asset, asset.status))
		if asset.company != self.company:
			frappe.throw(_("Row #{0}: asset {1} belongs to {2}.").format(row.idx, row.asset, asset.company))
		status = asset.al_rental_status or st.AVAILABLE
		if status not in (st.AVAILABLE, st.RESERVED):
			holder = _(" with {0}").format(asset.al_current_customer) if asset.al_current_customer else ""
			frappe.throw(
				_("Row #{0}: {1} is {2}{3} and cannot be dispatched.").format(row.idx, row.asset, status, holder),
				title=_("Equipment Not Available"),
			)
		if asset.location != self.from_location:
			frappe.throw(
				_("Row #{0}: {1} is at {2}, not at {3}. Dispatch it from the yard where it is.").format(
					row.idx, row.asset, asset.location or _("no recorded location"), self.from_location
				)
			)

	# ------------------------------------------------------------ submit
	def on_submit(self):
		self.agreement = self.get_agreement()
		movement = make_movement(
			self.company, self.doctype, self.name,
			[(row.asset, self.to_location) for row in self.items],
			self.dispatch_datetime,
		)
		self.db_set("asset_movement", movement)

		for row in self.items:
			if st.get_status(row.asset) == st.AVAILABLE:
				st.set_status(row.asset, st.RESERVED, reason=_("Held for dispatch {0}.").format(self.name))
			st.set_status(
				row.asset, st.ON_HIRE,
				reason=_("Dispatched to {0} for {1} on {2} ({3}).").format(
					self.to_location, self.customer, self.rental_agreement, self.name
				),
			)
			lifecycle.set_on_hire_holder(row.asset, self.rental_agreement, self.customer)
			row.db_set("previous_meter_reading", frappe.db.get_value("Asset", row.asset, "al_last_meter_reading"))
			if row.meter_reading_out:
				frappe.db.set_value("Asset", row.asset, "al_last_meter_reading", flt(row.meter_reading_out),
									update_modified=False)
			lifecycle.set_line(row.agreement_item, line_status=lifecycle.ON_HIRE,
							   dispatch_datetime=self.dispatch_datetime)

		lifecycle.refresh_agreement_status(self.rental_agreement)
		self.db_set("status", "Dispatched")

		if flt(self.agreement.mobilisation_charge) > 0:
			billing.try_create(
				billing.create_transport_invoice, self.agreement, "mobilisation", self.doctype, self.name,
				context=self.rental_agreement,
			)

	# ------------------------------------------------------------ cancel
	def before_cancel(self):
		self.validate_nothing_happened_since()

	def validate_nothing_happened_since(self):
		"""VAL-23 - a dispatch cannot be undone once the story has moved on."""
		rows = {row.agreement_item: row.asset for row in self.items}

		returned = frappe.get_all(
			"Rental Return Item",
			filters={"agreement_item": ["in", list(rows)], "docstatus": 1},
			fields=["parent", "asset"],
		)
		if returned:
			frappe.throw(
				_("Cannot cancel: {0} has already been returned on {1}. Cancel the return first.").format(
					returned[0].asset, returned[0].parent
				),
				title=_("Equipment Already Returned"),
			)

		logs = frappe.get_all(
			"Rental Downtime Log",
			filters={"rental_agreement": self.rental_agreement, "asset": ["in", list(rows.values())], "docstatus": 1},
			pluck="name",
		)
		if logs:
			frappe.throw(
				_("Cannot cancel: approved downtime {0} is recorded against this hire. Cancel it first.").format(
					", ".join(logs)
				)
			)

		for asset in rows.values():
			later = later_movements(asset, self.dispatch_datetime, exclude=self.asset_movement)
			if later:
				frappe.throw(
					_("Cannot cancel: {0} was moved again on {1} ({2}). Reverse that movement first.").format(
						asset, frappe.format(later[0].transaction_date, "Datetime"), later[0].name
					)
				)

	def on_cancel(self):
		cancel_movement(self.asset_movement)
		billing.delete_draft_invoices({"al_rental_dispatch": self.name})

		for row in self.items:
			st.set_status(row.asset, st.AVAILABLE, reversal_of=self.name)
			frappe.db.set_value("Asset", row.asset, "al_last_meter_reading", flt(row.previous_meter_reading),
								update_modified=False)
			lifecycle.set_line(row.agreement_item, line_status=lifecycle.PENDING, dispatch_datetime=None)
			lifecycle.refresh_asset_hold(row.asset)

		lifecycle.refresh_agreement_status(self.rental_agreement)
		self.db_set("status", "Cancelled")


@frappe.whitelist()
def get_pending_items(rental_agreement):
	"""Agreement lines still waiting to be dispatched. Read-only."""
	agreement = frappe.get_doc("Rental Agreement", rental_agreement)
	agreement.check_permission("read")
	yard = frappe.db.get_single_value("Asset Leasing Settings", "default_yard_location")
	rows = []
	for line in agreement.items:
		if line.line_status != lifecycle.PENDING:
			continue
		asset = frappe.db.get_value(
			"Asset", line.asset, ["location", "al_last_meter_reading", "al_rental_status"], as_dict=True
		)
		rows.append({
			"asset": line.asset,
			"asset_name": line.asset_name,
			"agreement_item": line.name,
			"location": asset.location,
			"rental_status": asset.al_rental_status,
			"meter_reading_out": asset.al_last_meter_reading,
		})
	locations = {r["location"] for r in rows if r["location"]}
	return {
		"items": rows,
		"from_location": locations.pop() if len(locations) == 1 else yard,
		"to_location": agreement.site_location,
	}
