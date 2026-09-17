"""Rental Return - equipment comes back and is inspected (AL-13, AL-14, AL-15).

The document is saved when the machine arrives, then goes through the Rental
Return Inspection workflow. Its effects happen on submit, which the workflow
only allows once inspection has passed, or once a Leasing Manager has
approved the recorded damage:

* one Asset Movement back to the receiving yard;
* each machine to Under Inspection, then to its chosen next status;
* the agreement line Returned, the agreement Partially Returned or Closed;
* hire days and the meter reading added to the machine;
* a draft damage invoice and an Asset Repair for each chargeable damage;
* on the final return, a draft demobilisation invoice.

* for a Short Term Hire, a draft rental invoice priced under the confirmed
  pro-rata policy (Q-14 to Q-18). A Long Term Contract is billed by its
  Subscription instead. On a site whose policy is not confirmed, the return
  records "Awaiting Pricing Policy" and no rent is calculated.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_datetime, getdate, now_datetime

from asset_leasing.rental import asset_status as st
from asset_leasing.rental import billing, lifecycle
from asset_leasing.rental.downtime import creditable_downtime_days
from asset_leasing.rental.movement import cancel_movement, later_movements, make_movement
from asset_leasing.rental import pricing
from asset_leasing.rental.pricing import elapsed_days
from asset_leasing.rental.validators import assert_yard_location

NEXT_STATUSES = (st.AVAILABLE, st.UNDER_INSPECTION, st.UNDER_REPAIR)
INSPECTED_STATES = ("Damage Assessed", "Inspected")


class RentalReturn(Document):
	def validate(self):
		self.agreement = frappe.get_doc("Rental Agreement", self.rental_agreement)
		self.set_party_from_agreement()
		self.validate_agreement()
		self.validate_route()
		self.validate_items()
		self.validate_inspection()
		self.validate_damages()
		self.validate_adjustment()
		self.set_rent()
		self.set_final_return()
		if self.docstatus == 0:
			self.status = "Draft"

	def set_party_from_agreement(self):
		"""VAL-11."""
		self.customer = self.agreement.customer
		self.customer_name = self.agreement.customer_name
		self.company = self.agreement.company
		self.currency = self.agreement.currency
		if self.rental_dispatch:
			dispatch_agreement = frappe.db.get_value("Rental Dispatch", self.rental_dispatch, "rental_agreement")
			if dispatch_agreement != self.rental_agreement:
				frappe.throw(_("Dispatch {0} belongs to agreement {1}.").format(self.rental_dispatch, dispatch_agreement))

	def validate_agreement(self):
		if self.agreement.docstatus != 1 or self.agreement.status not in ("Active", "Partially Returned"):
			frappe.throw(
				_("Agreement {0} is {1}; it has no equipment on hire to return.").format(
					self.agreement.name, self.agreement.status
				)
			)

	def validate_route(self):
		if frappe.db.get_value("Location", self.to_location, "is_group"):
			frappe.throw(_("{0} is a location group. Choose the actual yard.").format(self.to_location))
		assert_yard_location(self.to_location, _("Receiving Yard"))
		moment = get_datetime(self.return_datetime)
		if moment > now_datetime():
			frappe.throw(_("Return time {0} is in the future.").format(frappe.format(moment, "Datetime")))

	def validate_items(self):
		lines = {row.name: row for row in self.agreement.items}
		seen = set()
		self.total_elapsed_days = 0
		self.total_downtime_days = 0
		for row in self.items:
			line = self.resolve_line(row, lines)
			if row.asset in seen:
				frappe.throw(_("Row #{0}: equipment {1} appears twice.").format(row.idx, row.asset))
			seen.add(row.asset)

			# VAL-09 - only what is on hire under this agreement can come back on it.
			if line.line_status != lifecycle.ON_HIRE:
				frappe.throw(
					_("Row #{0}: {1} is {2} on agreement {3}, not On Hire.").format(
						row.idx, row.asset, line.line_status, self.agreement.name
					),
					title=_("Equipment Not On Hire"),
				)

			# VAL-01 - the defect that corrupted the prototype's only contract.
			if get_datetime(self.return_datetime) <= get_datetime(line.dispatch_datetime):
				frappe.throw(
					_("Row #{0}: {1} cannot be returned at {2} - it was dispatched at {3}. "
					  "The return must be after the dispatch.").format(
						row.idx, row.asset,
						frappe.format(get_datetime(self.return_datetime), "Datetime"),
						frappe.format(get_datetime(line.dispatch_datetime), "Datetime"),
					),
					title=_("Return Before Dispatch"),
				)

			self.fill_from_dispatch(row, line)

			# VAL-18 - a meter does not run backwards.
			if row.meter_reading_in is not None and flt(row.meter_reading_in) and row.meter_reading_out:
				if flt(row.meter_reading_in) < flt(row.meter_reading_out):
					frappe.throw(
						_("Row #{0}: meter reading in ({1}) is below the reading at dispatch ({2}) for {3}. "
						  "Check the entry or the meter.").format(
							row.idx, row.meter_reading_in, row.meter_reading_out, row.asset
						),
						title=_("Meter Reading Below Dispatch"),
					)
			row.meter_hours_used = (
				flt(row.meter_reading_in) - flt(row.meter_reading_out)
				if flt(row.meter_reading_in) and row.meter_reading_out is not None else 0
			)

			if row.post_return_status not in NEXT_STATUSES:
				frappe.throw(_("Row #{0}: choose the next status for {1}.").format(row.idx, row.asset))

			row.elapsed_days = elapsed_days(line.dispatch_datetime, self.return_datetime)
			row.downtime_days = creditable_downtime_days(
				self.rental_agreement, row.asset, line.dispatch_datetime, self.return_datetime
			)
			self.total_elapsed_days += flt(row.elapsed_days)
			self.total_downtime_days += flt(row.downtime_days)

	def resolve_line(self, row, lines):
		if row.agreement_item:
			line = lines.get(row.agreement_item)
			if not line or line.asset != row.asset:
				frappe.throw(_("Row #{0}: {1} is not on that line of agreement {2}.").format(
					row.idx, row.asset, self.agreement.name))
			return line
		matches = [l for l in lines.values() if l.asset == row.asset and l.line_status == lifecycle.ON_HIRE]
		if not matches:
			frappe.throw(
				_("Row #{0}: {1} is not on hire under agreement {2}.").format(row.idx, row.asset, self.agreement.name),
				title=_("Equipment Not On Hire"),
			)
		row.agreement_item = matches[0].name
		return matches[0]

	def fill_from_dispatch(self, row, line):
		"""Copy what was recorded when the machine left, as the comparison baseline."""
		row.dispatch_datetime = line.dispatch_datetime
		out = frappe.db.sql(
			"""
			select rdi.condition_out, rdi.meter_reading_out, rdi.fuel_level_out
			from `tabRental Dispatch Item` rdi
			join `tabRental Dispatch` rd on rd.name = rdi.parent
			where rdi.agreement_item = %s and rd.docstatus = 1
			order by rd.dispatch_datetime desc limit 1
			""",
			row.agreement_item,
			as_dict=True,
		)
		if out:
			row.condition_out = out[0].condition_out
			row.meter_reading_out = out[0].meter_reading_out
			row.fuel_level_out = out[0].fuel_level_out
		if self.docstatus == 0:
			row.source_location = frappe.db.get_value("Asset", row.asset, "location")

	def validate_inspection(self):
		if self.get("workflow_state") in INSPECTED_STATES or self.docstatus == 1:
			if not self.inspected_by:
				# Whoever completes the inspection step is the inspector of record.
				self.inspected_by = frappe.session.user
			if self.inspection_result == "Pending":
				frappe.throw(_("Record the inspection result before completing the inspection."))
			if not self.inspected_by:
				frappe.throw(_("<b>Inspected By</b> is required before the inspection is completed."))

	def validate_damages(self):
		"""VAL-19."""
		assets = {row.asset for row in self.items}
		if self.inspection_result == "Damage Found" and not self.damages:
			frappe.throw(_("Inspection found damage - record at least one damage row."))
		if self.inspection_result == "Passed" and self.damages:
			frappe.throw(_("Inspection is marked Passed but damage rows are recorded. Choose Damage Found."))

		self.total_damage_estimate = 0
		self.total_chargeable_damage = 0
		for d in self.damages:
			if d.asset not in assets:
				frappe.throw(_("Damage row #{0}: {1} is not being returned on this document.").format(d.idx, d.asset))
			if flt(d.estimated_cost) < 0:
				frappe.throw(_("Damage row #{0}: estimated cost cannot be negative.").format(d.idx))
			if d.chargeable_to_customer and flt(d.estimated_cost) <= 0:
				frappe.throw(
					_("Damage row #{0}: a chargeable damage needs an estimated cost above zero.").format(d.idx)
				)
			self.total_damage_estimate += flt(d.estimated_cost)
			if d.chargeable_to_customer:
				self.total_chargeable_damage += flt(d.estimated_cost)

		# A chargeable repair job will be opened for these machines, so they cannot go straight back to Available.
		needs_repair = {d.asset for d in self.damages if d.chargeable_to_customer and d.severity != "Total Loss"}
		for row in self.items:
			if row.asset in needs_repair and row.post_return_status != st.UNDER_REPAIR:
				frappe.throw(
					_("Row #{0}: {1} has chargeable damage and a repair job will be opened, "
					  "so its next status must be Under Repair.").format(row.idx, row.asset)
				)
		total_loss = {d.asset for d in self.damages if d.severity == "Total Loss"}
		for row in self.items:
			if row.asset in total_loss and row.post_return_status == st.AVAILABLE:
				frappe.throw(_("Row #{0}: {1} is recorded as a total loss and cannot be made Available.").format(
					row.idx, row.asset))

	def validate_adjustment(self):
		"""VAL-20 - a credit needs a reason and cannot exceed the hire."""
		if flt(self.adjustment_days) and not (self.adjustment_reason or "").strip():
			frappe.throw(_("Give a reason for the adjustment of {0} days.").format(self.adjustment_days))
		if self.waive_overdue_surcharge and not (self.adjustment_reason or "").strip():
			frappe.throw(_("Give a reason for waiving the overdue surcharge."))
		if flt(self.adjustment_days) < 0:
			frappe.throw(_("Adjustment days cannot be negative - an adjustment is a credit."))
		for row in self.items:
			net = flt(row.elapsed_days) - flt(row.downtime_days) - flt(self.adjustment_days)
			if net < 0:
				frappe.throw(
					_("Row #{0}: downtime and adjustment ({1} days) exceed the hire of {2} ({3} days).").format(
						row.idx, flt(flt(row.downtime_days) + flt(self.adjustment_days), 2),
						row.asset, flt(row.elapsed_days, 2),
					)
				)

	def set_rent(self):
		"""Billable days and rent per machine, recomputed on every save.

		Whatever the browser sent is discarded - the figures on an invoice come
		from here only.
		"""
		short_term = self.agreement.agreement_type == billing.SHORT_TERM
		priced = short_term and pricing.policy_ready()
		lines = {line.name: line for line in self.agreement.items}
		self.total_billable_days = 0
		self.computed_rental_amount = 0
		for row in self.items:
			line = lines[row.agreement_item]
			row.overdue_days = pricing.overdue_days(self.agreement.expected_end_date, self.return_datetime) \
				if pricing.policy_ready() else 0
			if not priced:
				row.billable_days = None
				row.rental_amount = None
				continue
			result = billing.price_return_line(self, row, self.agreement)
			row.billable_days = result.billable_days
			row.rental_amount = 0 if line.is_free_of_charge else result.amount
			self.total_billable_days += flt(row.billable_days)
			self.computed_rental_amount += flt(row.rental_amount)
		if not priced:
			self.total_billable_days = None
			self.computed_rental_amount = None

	def set_final_return(self):
		returning = {row.agreement_item for row in self.items}
		outstanding = [
			l for l in self.agreement.items
			if l.line_status in (lifecycle.PENDING, lifecycle.ON_HIRE) and l.name not in returning
		]
		self.is_final_return = 0 if outstanding else 1

	# ------------------------------------------------------------ submit
	def before_submit(self):
		"""Damage reaches an invoice only with a Leasing Manager's approval.

		The workflow routes Damage Found through the manager, but submit
		permission is shared with the technician (for Pass Inspection), so the
		rule is also held here, where the API cannot step around it.
		"""
		if self.inspection_result == "Damage Found" and not (
			{"Leasing Manager", "System Manager"} & set(frappe.get_roles())
		):
			frappe.throw(
				_("Recorded damage must be approved by a Leasing Manager before this return is completed."),
				frappe.PermissionError,
				title=_("Manager Approval Required"),
			)

	def on_submit(self):
		self.agreement = frappe.get_doc("Rental Agreement", self.rental_agreement)
		movement = make_movement(
			self.company, self.doctype, self.name,
			[(row.asset, self.to_location) for row in self.items],
			self.return_datetime,
		)
		self.db_set("asset_movement", movement)

		for row in self.items:
			self.receive_asset(row)
			lifecycle.set_line(
				row.agreement_item,
				line_status=lifecycle.RETURNED,
				return_datetime=self.return_datetime,
				billable_days=row.billable_days,
				line_amount=row.rental_amount,
			)

		self.open_repairs()
		lifecycle.refresh_agreement_status(self.rental_agreement)
		self.db_set("status", "Inspected")
		self.bill()

		if self.is_final_return:
			closed = frappe.get_doc("Rental Agreement", self.rental_agreement)
			closed.add_comment("Info", _("Closed by final return {0}.").format(self.name))
			closed.run_method("al_agreement_closed")

	def receive_asset(self, row):
		asset = row.asset
		st.set_status(asset, st.UNDER_INSPECTION, reason=_("Received at {0} on return {1}.").format(
			self.to_location, self.name))
		if row.post_return_status != st.UNDER_INSPECTION:
			st.set_status(asset, row.post_return_status, reason=_("Inspection on {0}: {1}.").format(
				self.name, self.inspection_result))

		values = frappe.db.get_value("Asset", asset, ["al_total_hire_days", "al_last_meter_reading"], as_dict=True)
		row.db_set("previous_meter_reading", values.al_last_meter_reading)
		update = {"al_total_hire_days": flt(values.al_total_hire_days) + flt(row.elapsed_days)}
		if flt(row.meter_reading_in):
			update["al_last_meter_reading"] = flt(row.meter_reading_in)
		frappe.db.set_value("Asset", asset, update, update_modified=False)
		lifecycle.refresh_asset_hold(asset)

	def open_repairs(self):
		"""AL-15 / AL-21 - a repair job for each chargeable damage."""
		for d in self.damages:
			if not d.chargeable_to_customer:
				continue
			if d.severity == "Total Loss":
				frappe.get_doc("Asset", d.asset).add_comment(
					"Info",
					_("Recorded as a total loss on {0}. Dispose of it through the standard ERPNext "
					  "Asset workflow once the recovery is settled.").format(self.name),
				)
				continue
			repair = frappe.get_doc({
				"doctype": "Asset Repair",
				"asset": d.asset,
				"company": self.company,
				"failure_date": self.return_datetime,
				"repair_status": "Pending",
				"description": _("{0} damage found on return {1}: {2}").format(d.severity, self.name, d.damage_description),
				"al_chargeable_to_customer": 1,
				"al_customer": self.customer,
				"al_rental_return": self.name,
			})
			repair.flags.ignore_permissions = True
			repair.insert()

	def bill(self):
		status = billing.rental_billing_status(self, self.agreement.agreement_type)
		if status is None:
			name = billing.try_create(billing.create_rental_invoice, self, context=self.rental_agreement)
			status = billing.INVOICED if name else billing.AWAITING_POLICY
		self.db_set("rental_billing_status", status)

		if self.total_chargeable_damage:
			billing.try_create(billing.create_damage_invoice, self, context=self.rental_agreement)
		if self.is_final_return and flt(self.agreement.demobilisation_charge) > 0:
			billing.try_create(
				billing.create_transport_invoice, self.agreement, "demobilisation", self.doctype, self.name,
				context=self.rental_agreement,
			)

	# ------------------------------------------------------------ cancel
	def before_cancel(self):
		"""VAL-24 - a submitted invoice must be cancelled deliberately first."""
		invoices = frappe.get_all(
			"Sales Invoice", filters={"al_rental_return": self.name, "docstatus": 1}, pluck="name"
		)
		if invoices:
			frappe.throw(
				_("Cannot cancel: invoice {0} raised from this return is submitted. Cancel it first.").format(
					", ".join(invoices)
				),
				title=_("Invoice Already Submitted"),
			)
		for row in self.items:
			later = later_movements(row.asset, self.return_datetime, exclude=self.asset_movement)
			if later:
				frappe.throw(
					_("Cannot cancel: {0} has moved since this return ({1}). Reverse that first.").format(
						row.asset, later[0].name
					)
				)
			if st.get_status(row.asset) not in (row.post_return_status, st.RESERVED, st.AVAILABLE, st.UNDER_REPAIR):
				frappe.throw(
					_("Cannot cancel: {0} is now {1}.").format(row.asset, st.get_status(row.asset))
				)
		submitted_repairs = frappe.get_all(
			"Asset Repair", filters={"al_rental_return": self.name, "docstatus": 1}, pluck="name"
		)
		if submitted_repairs:
			frappe.throw(_("Cannot cancel: repair {0} is already completed.").format(", ".join(submitted_repairs)))

	def on_cancel(self):
		for name in frappe.get_all("Asset Repair", filters={"al_rental_return": self.name, "docstatus": 0}, pluck="name"):
			frappe.delete_doc("Asset Repair", name, ignore_permissions=True)
		billing.delete_draft_invoices({"al_rental_return": self.name})
		cancel_movement(self.asset_movement)

		for row in self.items:
			values = frappe.db.get_value("Asset", row.asset, ["al_total_hire_days"], as_dict=True)
			frappe.db.set_value(
				"Asset", row.asset,
				{
					"al_total_hire_days": max(0.0, flt(values.al_total_hire_days) - flt(row.elapsed_days)),
					"al_last_meter_reading": flt(row.previous_meter_reading),
				},
				update_modified=False,
			)
			st.set_status(row.asset, st.ON_HIRE, reversal_of=self.name)
			lifecycle.set_on_hire_holder(row.asset, self.rental_agreement, self.customer)
			lifecycle.set_line(row.agreement_item, line_status=lifecycle.ON_HIRE, return_datetime=None,
							   billable_days=None, line_amount=None)

		lifecycle.refresh_agreement_status(self.rental_agreement)
		self.db_set("status", "Cancelled")


@frappe.whitelist()
def get_on_hire_items(rental_agreement, rental_dispatch=None):
	"""Machines currently on hire under the agreement. Read-only."""
	agreement = frappe.get_doc("Rental Agreement", rental_agreement)
	agreement.check_permission("read")
	lines = [l for l in agreement.items if l.line_status == lifecycle.ON_HIRE]
	if rental_dispatch:
		wanted = set(frappe.get_all(
			"Rental Dispatch Item", filters={"parent": rental_dispatch}, pluck="agreement_item"
		))
		lines = [l for l in lines if l.name in wanted]
	yard = frappe.db.get_single_value("Asset Leasing Settings", "default_yard_location")
	rows = []
	for line in lines:
		asset = frappe.db.get_value("Asset", line.asset, ["location", "al_base_location"], as_dict=True)
		rows.append({
			"asset": line.asset,
			"asset_name": line.asset_name,
			"agreement_item": line.name,
			"dispatch_datetime": line.dispatch_datetime,
			"source_location": asset.location,
			"home_yard": asset.al_base_location,
		})
	homes = {r["home_yard"] for r in rows if r["home_yard"]}
	return {"items": rows, "to_location": homes.pop() if len(homes) == 1 else yard}


@frappe.whitelist()
def preview_return(rental_agreement, return_datetime, items, adjustment_days=0):
	"""Days and rent before submission. Indicative only - recomputed on save."""
	agreement = frappe.get_doc("Rental Agreement", rental_agreement)
	agreement.check_permission("read")

	items = frappe.parse_json(items) or []
	priced = agreement.agreement_type == billing.SHORT_TERM and pricing.policy_ready()
	lines = {l.asset: l for l in agreement.items if l.line_status == lifecycle.ON_HIRE}
	out = []
	for row in items:
		line = lines.get(row.get("asset"))
		entry = {"asset": row.get("asset"), "elapsed_days": None, "downtime_days": None,
				 "billable_days": None, "rental_amount": None}
		if line and get_datetime(return_datetime) > get_datetime(line.dispatch_datetime):
			downtime = creditable_downtime_days(rental_agreement, line.asset, line.dispatch_datetime, return_datetime)
			entry.update(
				elapsed_days=elapsed_days(line.dispatch_datetime, return_datetime),
				downtime_days=downtime,
			)
			if priced and flt(entry["elapsed_days"]) - downtime - flt(adjustment_days) >= 0:
				result = pricing.price_hire(line.monthly_rate, line.dispatch_datetime, return_datetime,
											downtime, flt(adjustment_days))
				entry.update(billable_days=result.billable_days,
							 rental_amount=0 if line.is_free_of_charge else result.amount,
							 daily_rate=result.daily_rate, divisor=result.divisor)
		out.append(entry)
	return {
		"items": out,
		"agreement_type": agreement.agreement_type,
		"pricing_pending": [] if agreement.agreement_type == billing.LONG_TERM else pricing.pending_policy_questions(),
	}
