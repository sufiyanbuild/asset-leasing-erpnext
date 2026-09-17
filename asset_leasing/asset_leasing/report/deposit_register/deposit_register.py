"""AL-10 - deposits agreed, received, refunded, held and refundable."""

import frappe
from frappe import _
from frappe.utils import flt

from asset_leasing.reports_common import require
from asset_leasing.rental import deposits


def execute(filters=None):
	filters = frappe._dict(filters or {})
	require(filters, "company")
	tagged = set(frappe.get_all("Payment Entry", filters={"al_deposit_type": ["is", "set"], "docstatus": 1,
															"company": filters.company}, pluck="al_rental_agreement"))
	conditions = {"company": filters.company, "docstatus": 1}
	if filters.customer:
		conditions["customer"] = filters.customer
	rows = []
	for a in frappe.get_all("Rental Agreement", filters=conditions,
							fields=["name", "customer", "status", "security_deposit_amount"], order_by="name"):
		if not flt(a.security_deposit_amount) and a.name not in tagged:
			continue
		totals = deposits.agreement_deposit_totals(a.name)
		damage = deposits.outstanding_damage(a.name)
		rows.append({
			"agreement": a.name, "customer": a.customer, "status": a.status,
			"agreed": flt(a.security_deposit_amount), "received": totals.received, "refunded": totals.refunded,
			"held": totals.held, "damage_outstanding": damage,
			"refundable": deposits.refundable_amount(a.name, a.customer, filters.company),
			"customer_balance": deposits.customer_deposit_balance(a.customer, filters.company),
		})
	columns = [
		{"label": _("Agreement"), "fieldname": "agreement", "fieldtype": "Link", "options": "Rental Agreement", "width": 130},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 180},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
		{"label": _("Agreed Deposit"), "fieldname": "agreed", "fieldtype": "Currency", "width": 120},
		{"label": _("Received"), "fieldname": "received", "fieldtype": "Currency", "width": 110},
		{"label": _("Refunded"), "fieldname": "refunded", "fieldtype": "Currency", "width": 110},
		{"label": _("Held"), "fieldname": "held", "fieldtype": "Currency", "width": 110},
		{"label": _("Damage Not Yet Recovered"), "fieldname": "damage_outstanding", "fieldtype": "Currency", "width": 170},
		{"label": _("Refundable"), "fieldname": "refundable", "fieldtype": "Currency", "width": 110},
		{"label": _("Customer Deposit Ledger"), "fieldname": "customer_balance", "fieldtype": "Currency", "width": 160},
	]
	message = None
	if not frappe.db.get_single_value("Asset Leasing Settings", "deposit_liability_account"):
		message = _("Set the Security Deposit Liability Account in Asset Leasing Settings to record deposits.")
	return columns, rows, message
