import frappe
from frappe import _
from frappe.model.document import Document

from asset_leasing.rental.pricing import UNRESOLVED_POLICY
from asset_leasing.rental.validators import assert_not_fixed_asset_item


class AssetLeasingSettings(Document):
	def validate(self):
		self.validate_pricing_policy_complete()
		self.validate_minimum_period()
		self.validate_billing_items()
		self.validate_accounts()
		if self.overdue_grace_days is not None and self.overdue_grace_days < 0:
			frappe.throw(_("Overdue Grace Days cannot be negative."))
		if self.overdue_surcharge_percent and self.overdue_surcharge_percent < 0:
			frappe.throw(_("Overdue Surcharge % cannot be negative."))

	def on_update(self):
		frappe.clear_document_cache(self.doctype, self.name)

	def validate_billing_items(self):
		for field in ("damage_charge_item", "transport_charge_item"):
			if self.get(field):
				assert_not_fixed_asset_item(self.get(field), self.meta.get_label(field))

	def validate_accounts(self):
		if self.deposit_liability_account:
			acc = frappe.db.get_value(
				"Account", self.deposit_liability_account, ["root_type", "is_group", "account_type"], as_dict=True
			)
			if acc.root_type != "Liability" or acc.is_group:
				frappe.throw(_("The Security Deposit Liability Account must be a Liability ledger, not a group."))
			if acc.account_type:
				frappe.throw(
					_("The Security Deposit Liability Account must have no Account Type (it is {0}). "
					  "A Receivable or Payable type would mix deposits into customer balances.").format(acc.account_type)
				)
		if self.damage_income_account:
			acc = frappe.db.get_value("Account", self.damage_income_account, ["root_type", "is_group"], as_dict=True)
			if acc.root_type != "Income" or acc.is_group:
				frappe.throw(_("The Damage Recovery Income Account must be an Income ledger, not a group."))

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
