import frappe
from frappe import _
from frappe.model.document import Document

from asset_leasing.rental.pricing import UNRESOLVED_POLICY


class AssetLeasingSettings(Document):
	def validate(self):
		self.validate_pricing_policy_complete()
		self.validate_minimum_period()

	def validate_pricing_policy_complete(self):
		"""Refuse a half-answered pricing policy.

		Ticking the confirmation box with fields still blank would let the
		pricing engine run on partial information, which is the exact failure
		the box exists to prevent.
		"""
		if not self.pricing_policy_confirmed:
			return
		missing = [q for f, q in UNRESOLVED_POLICY.items() if not self.get(f)]
		if missing:
			frappe.throw(
				_("Cannot confirm the pricing policy while these are unanswered:<br>{0}").format(
					"<br>".join(f"&bull; {q}" for q in missing)
				),
				title=_("Pricing Policy Incomplete"),
			)

	def validate_minimum_period(self):
		if self.has_minimum_rental_period == "Yes" and not self.minimum_billable_days:
			frappe.throw(_("Set Minimum Billable Days, or set the minimum rental period to No."))
		if self.minimum_billable_days and self.minimum_billable_days < 0:
			frappe.throw(_("Minimum Billable Days cannot be negative."))
