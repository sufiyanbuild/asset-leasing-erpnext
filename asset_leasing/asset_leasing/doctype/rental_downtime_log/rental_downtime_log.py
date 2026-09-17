"""Rental Downtime Log - time a hired machine could not be used (AL-18).

Approval (Rental Downtime Approval workflow) is the submit. Only an approved
log with Is Creditable ticked reduces the chargeable duration. Which reasons
should be creditable is the client's call (Q-06); the Leasing Manager applies
it when approving, and nothing here decides it automatically.

A machine's downtime must be settled before its return is submitted - the
return captures the approved downtime at that moment.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_datetime, now_datetime

from asset_leasing.rental import lifecycle


class RentalDowntimeLog(Document):
	def validate(self):
		agreement = frappe.db.get_value(
			"Rental Agreement", self.rental_agreement,
			["docstatus", "customer", "customer_name", "company"], as_dict=True,
		)
		if not agreement or agreement.docstatus != 1:
			frappe.throw(_("Downtime is recorded against an approved agreement."))
		self.customer, self.customer_name, self.company = agreement.customer, agreement.customer_name, agreement.company

		self.validate_window()
		self.line = self.get_line()
		self.validate_within_hire()
		self.validate_no_overlap()
		self.downtime_hours = flt(
			(get_datetime(self.to_datetime) - get_datetime(self.from_datetime)).total_seconds() / 3600.0, 2
		)
		if self.is_creditable and not (self.remarks or "").strip():
			frappe.throw(_("Explain the downtime in <b>Remarks</b> when it is creditable."))

	def validate_window(self):
		start, end = get_datetime(self.from_datetime), get_datetime(self.to_datetime)
		if end <= start:
			frappe.throw(_("<b>To</b> must be after <b>From</b>."))
		if end > now_datetime():
			frappe.throw(_("Downtime cannot be recorded for the future."))

	def get_line(self):
		lines = frappe.get_all(
			"Rental Agreement Item",
			filters={"parent": self.rental_agreement, "parenttype": "Rental Agreement", "asset": self.asset,
					 "line_status": ["in", [lifecycle.ON_HIRE, lifecycle.RETURNED]]},
			fields=["name", "line_status", "dispatch_datetime", "return_datetime"],
			order_by="dispatch_datetime desc",
		)
		if not lines:
			frappe.throw(
				_("{0} has not been dispatched on agreement {1}, so it cannot have downtime.").format(
					self.asset, self.rental_agreement
				)
			)
		return lines[0]

	def validate_within_hire(self):
		"""VAL-04 - inside the hire window, and before the return is settled."""
		start, end = get_datetime(self.from_datetime), get_datetime(self.to_datetime)
		if start < get_datetime(self.line.dispatch_datetime):
			frappe.throw(
				_("Downtime starts before {0} was dispatched ({1}).").format(
					self.asset, frappe.format(get_datetime(self.line.dispatch_datetime), "Datetime")
				)
			)
		if self.line.line_status != lifecycle.RETURNED:
			return
		returned = get_datetime(self.line.return_datetime)
		if end > returned:
			frappe.throw(
				_("Downtime ends after {0} was returned ({1}).").format(
					self.asset, frappe.format(returned, "Datetime")
				)
			)
		if self.is_creditable:
			frappe.throw(
				_("{0} was returned on {1}. Creditable downtime must be approved before the return is "
				  "submitted; this log can only be kept as a non-creditable record.").format(
					self.asset, frappe.format(returned, "Datetime")
				),
				title=_("Hire Already Returned"),
			)

	def validate_no_overlap(self):
		others = frappe.get_all(
			"Rental Downtime Log",
			filters={
				"rental_agreement": self.rental_agreement, "asset": self.asset,
				"docstatus": 1, "name": ["!=", self.name or ""],
				"from_datetime": ["<", self.to_datetime], "to_datetime": [">", self.from_datetime],
			},
			fields=["name", "from_datetime", "to_datetime"],
		)
		if others:
			o = others[0]
			frappe.throw(
				_("This period overlaps approved downtime {0} ({1} to {2}).").format(
					o.name, frappe.format(o.from_datetime, "Datetime"), frappe.format(o.to_datetime, "Datetime")
				),
				title=_("Overlapping Downtime"),
			)

	def on_submit(self):
		self.db_set("approved_by", frappe.session.user)

	def before_cancel(self):
		line = self.get_line()
		if self.is_creditable and line.line_status == lifecycle.RETURNED:
			frappe.throw(_("{0} has already been returned; its approved downtime can no longer be withdrawn.").format(
				self.asset))


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def hired_asset_query(doctype, txt, searchfield, start, page_len, filters):
	"""Machines that have been dispatched on the chosen agreement."""
	agreement = (filters or {}).get("rental_agreement")
	if not agreement:
		return []
	frappe.get_doc("Rental Agreement", agreement).check_permission("read")
	rows = frappe.get_all(
		"Rental Agreement Item",
		filters={"parent": agreement, "parenttype": "Rental Agreement",
				 "line_status": ["in", [lifecycle.ON_HIRE, lifecycle.RETURNED]]},
		fields=["asset", "asset_name", "line_status"],
		order_by="idx",
	)
	txt = (txt or "").lower()
	rows = [r for r in rows if txt in (r.asset or "").lower() or txt in (r.asset_name or "").lower()]
	start, page_len = int(start or 0), int(page_len or 20)
	return [(r.asset, r.asset_name, r.line_status) for r in rows[start:start + page_len]]
