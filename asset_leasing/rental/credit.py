"""Credit control (VAL-15, AL-05).

Uses ERPNext's own credit limit and outstanding figures - the Customer Credit
Limit table and the GL-based outstanding - rather than a parallel calculation.

Checked twice: on every save and at dispatch against the exposure that
already exists, and at approval with the agreement's own estimated value added
("would this hire push the customer over the limit"). An open-ended hire has no
estimated value, so only the existing exposure is tested for it.
"""

import frappe
from frappe import _
from frappe.utils import flt

SETTINGS = "Asset Leasing Settings"


def get_credit_position(customer, company):
	from erpnext.selling.doctype.customer.customer import get_credit_limit, get_customer_outstanding

	limit = flt(get_credit_limit(customer, company))
	if not limit:
		return None
	outstanding = flt(get_customer_outstanding(customer, company))
	return frappe._dict(limit=limit, outstanding=outstanding, exceeded=outstanding > limit)


def assert_within_credit_limit(customer, company, action, additional_exposure=0):
	"""Refuse when the customer's exposure would exceed its credit limit."""
	if not (customer and company):
		return
	if not frappe.get_cached_doc(SETTINGS).block_dispatch_if_credit_exceeded:
		return
	position = get_credit_position(customer, company)
	if not position:
		return
	exposure = position.outstanding + flt(additional_exposure)
	if exposure <= position.limit:
		return
	detail = (
		_("{0} outstanding plus {1} for this agreement").format(
			frappe.format(position.outstanding, {"fieldtype": "Currency"}),
			frappe.format(additional_exposure, {"fieldtype": "Currency"}),
		)
		if flt(additional_exposure) else
		_("{0} outstanding").format(frappe.format(position.outstanding, {"fieldtype": "Currency"}))
	)
	frappe.throw(
		_("Customer {0} would exceed its credit limit of {1} ({2}), so {3} is blocked. "
		  "Collect payment or raise the limit first.").format(
			customer, frappe.format(position.limit, {"fieldtype": "Currency"}), detail, action,
		),
		title=_("Credit Limit Exceeded"),
	)
