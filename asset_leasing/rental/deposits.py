"""Security deposits (AL-10) on standard Payment Entry.

A deposit is money held, not revenue, so it never allocates against an invoice.
It is a Payment Entry with the customer as party whose party account is the
Security Deposit Liability Account from Asset Leasing Settings:

    Deposit Received  - payment type Receive, Cr deposit liability
    Deposit Refund    - payment type Pay,     Dr deposit liability

The entry is tagged with the agreement (al_rental_agreement) and the kind
(al_deposit_type). The app adds no ledger logic of its own.

Open decisions this respects: Q-04 (deposit basis - an amount entered per
agreement is the working default) and Q-22 (held per customer or per
agreement - both views are maintained). A manual offset of deposit against a
damage invoice (Q-07 working default) is a Finance Journal Entry, which the
customer-level balance reflects because it is read from the ledger.
"""

import frappe
from frappe import _
from frappe.utils import flt

SETTINGS = "Asset Leasing Settings"
RECEIVED = "Deposit Received"
REFUND = "Deposit Refund"


def deposit_account():
	return frappe.get_cached_doc(SETTINGS).deposit_liability_account


def agreement_deposit_totals(agreement, exclude=None):
	rows = frappe.db.sql(
		"""
		select al_deposit_type, coalesce(sum(paid_amount), 0) as amount
		from `tabPayment Entry`
		where al_rental_agreement = %s and docstatus = 1 and name != %s
		group by al_deposit_type
		""",
		(agreement, exclude or ""),
		as_dict=True,
	)
	totals = {r.al_deposit_type: flt(r.amount) for r in rows}
	received, refunded = totals.get(RECEIVED, 0.0), totals.get(REFUND, 0.0)
	return frappe._dict(received=received, refunded=refunded, held=received - refunded)


def customer_deposit_balance(customer, company=None):
	"""Credit balance of the deposit liability account for this customer."""
	account = deposit_account()
	if not account:
		return 0.0
	company_clause = "and company = %(company)s" if company else ""
	balance = frappe.db.sql(
		f"""
		select coalesce(sum(credit_in_account_currency) - sum(debit_in_account_currency), 0)
		from `tabGL Entry`
		where account = %(account)s and party_type = 'Customer' and party = %(party)s
			and is_cancelled = 0 {company_clause}
		""",
		{"account": account, "party": customer, "company": company},
	)[0][0]
	return flt(balance)


def outstanding_damage(agreement):
	"""Approved damage not yet recovered.

	Unpaid balance of submitted damage invoices, plus approved chargeable damage
	on submitted returns whose invoice is still a draft or was never raised.
	"""
	unpaid = flt(frappe.db.sql(
		"""select coalesce(sum(outstanding_amount), 0) from `tabSales Invoice`
		where al_rental_agreement = %s and al_invoice_purpose = 'Damage Recovery' and docstatus = 1""",
		agreement,
	)[0][0])

	uninvoiced = 0.0
	for ret in frappe.get_all("Rental Return", filters={"rental_agreement": agreement, "docstatus": 1}, pluck="name"):
		if frappe.db.exists("Sales Invoice", {
			"al_rental_return": ret, "al_invoice_purpose": "Damage Recovery", "docstatus": 1,
		}):
			continue
		uninvoiced += flt(frappe.db.sql(
			"""select coalesce(sum(estimated_cost), 0) from `tabRental Damage Item`
			where parent = %s and parenttype = 'Rental Return' and chargeable_to_customer = 1""",
			ret,
		)[0][0])
	return unpaid + uninvoiced


def refundable_amount(agreement, customer, company, exclude=None):
	"""VAL-21: what may still be refunded on this agreement."""
	held = agreement_deposit_totals(agreement, exclude=exclude).held
	ledger = customer_deposit_balance(customer, company)
	return max(0.0, min(held, ledger) - outstanding_damage(agreement))


# ------------------------------------------------------------ doc events
def validate(doc, method=None):
	kind = doc.get("al_deposit_type")
	if not kind:
		return

	agreement_name = doc.get("al_rental_agreement")
	if not agreement_name:
		frappe.throw(_("A security deposit must name its <b>Rental Agreement</b>."))
	agreement = frappe.db.get_value(
		"Rental Agreement", agreement_name,
		["docstatus", "customer", "company", "security_deposit_amount"], as_dict=True,
	)
	if not agreement or agreement.docstatus != 1:
		frappe.throw(_("Deposits are recorded against an approved agreement. {0} is not approved.").format(agreement_name))
	if doc.party_type != "Customer" or doc.party != agreement.customer:
		frappe.throw(_("The deposit party must be {0}, the customer on {1}.").format(agreement.customer, agreement_name))
	if doc.company != agreement.company:
		frappe.throw(_("Company must be {0}, as on {1}.").format(agreement.company, agreement_name))

	account = deposit_account()
	if not account:
		frappe.throw(
			_("Set the <b>Security Deposit Liability Account</b> in {0} before recording deposits.").format(SETTINGS),
			title=_("Deposit Account Not Configured"),
		)

	expected_type = "Receive" if kind == RECEIVED else "Pay"
	if doc.payment_type != expected_type:
		frappe.throw(_("A {0} must use payment type {1}.").format(kind, expected_type))

	party_account = doc.paid_from if kind == RECEIVED else doc.paid_to
	if party_account != account:
		frappe.throw(
			_("A {0} must post to the deposit liability account {1}, not {2}. "
			  "(If the company books advances in a separate party account, that setting overrides the "
			  "account; record deposits with it switched off.)").format(kind, account, party_account),
			title=_("Wrong Deposit Account"),
		)

	if any(flt(r.allocated_amount) for r in doc.get("references") or []):
		frappe.throw(_("A deposit is held, not applied - remove the invoice allocations."))

	if kind == RECEIVED:
		already = agreement_deposit_totals(agreement_name, exclude=doc.name).received
		agreed = flt(agreement.security_deposit_amount)
		if agreed and already + flt(doc.paid_amount) > agreed:
			frappe.msgprint(
				_("This brings deposits received on {0} to {1}, above the agreed {2}.").format(
					agreement_name,
					frappe.format(already + flt(doc.paid_amount), {"fieldtype": "Currency"}),
					frappe.format(agreed, {"fieldtype": "Currency"}),
				),
				indicator="orange", alert=True,
			)
	else:
		limit = refundable_amount(agreement_name, agreement.customer, agreement.company, exclude=doc.name)
		if flt(doc.paid_amount) > flt(limit) + 0.005:
			frappe.throw(
				_("Refund of {0} exceeds the refundable deposit on {1}: {2} (deposit held, less approved "
				  "damage not yet recovered).").format(
					frappe.format(doc.paid_amount, {"fieldtype": "Currency"}),
					agreement_name,
					frappe.format(limit, {"fieldtype": "Currency"}),
				),
				title=_("Refund Exceeds Deposit"),
			)


def on_submit(doc, method=None):
	if doc.get("al_deposit_type"):
		refresh_deposit_state(doc.al_rental_agreement, doc.party, doc.company)


def on_cancel(doc, method=None):
	on_submit(doc, method)


def refresh_deposit_state(agreement, customer, company=None):
	totals = agreement_deposit_totals(agreement)
	frappe.db.set_value(
		"Rental Agreement", agreement,
		{"deposit_held": totals.held, "deposit_received": 1 if totals.received > 0 else 0},
		update_modified=False,
	)
	frappe.db.set_value(
		"Customer", customer, "al_deposit_held", max(0.0, customer_deposit_balance(customer)),
		update_modified=False,
	)


@frappe.whitelist()
def make_deposit_entry(agreement, kind):
	"""A prepared, unsaved Payment Entry for the deposit or its refund."""
	frappe.has_permission("Payment Entry", "create", throw=True)
	doc = frappe.get_doc("Rental Agreement", agreement)
	doc.check_permission("read")
	if kind not in (RECEIVED, REFUND):
		frappe.throw(_("Unknown deposit entry type {0}.").format(kind))
	account = deposit_account()
	if not account:
		frappe.throw(_("Set the <b>Security Deposit Liability Account</b> in {0} first.").format(SETTINGS))

	pe = frappe.new_doc("Payment Entry")
	pe.payment_type = "Receive" if kind == RECEIVED else "Pay"
	pe.company = doc.company
	pe.party_type = "Customer"
	pe.party = doc.customer
	pe.al_rental_agreement = doc.name
	pe.al_deposit_type = kind
	cash = frappe.get_cached_value("Company", doc.company, "default_bank_account") or \
		frappe.get_cached_value("Company", doc.company, "default_cash_account")
	if kind == RECEIVED:
		amount = max(0.0, flt(doc.security_deposit_amount) - agreement_deposit_totals(doc.name).received)
		pe.paid_from, pe.paid_to = account, cash
	else:
		amount = refundable_amount(doc.name, doc.customer, doc.company)
		pe.paid_from, pe.paid_to = cash, account
	pe.paid_amount = pe.received_amount = amount
	pe.remarks = _("{0} for Rental Agreement {1}").format(kind, doc.name)
	pe.setup_party_account_field()
	pe.set_missing_values()
	pe.set_exchange_rate()
	return pe.as_dict()
