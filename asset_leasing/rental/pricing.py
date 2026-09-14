"""Pricing for equipment hire.

Confirmed business rule (Q-01, client-confirmed):

    A fixed monthly rate is the only commercial rental rate. The agreed rate for
    the Excavator EX-200 is INR 45,000 per month. Rentals shorter than one month
    are billed pro rata, derived from that monthly rate.

    This is NOT a tiered model. There are no daily or weekly price lists, no
    duration bands, no tier thresholds and no tier-selection engine.

Deliberately NOT implemented (Q-14 to Q-18, unresolved business policy):

    Q-14  Is the monthly rate divided by a fixed 30, or by the actual number of
          days in the calendar month?
    Q-15  Is there a minimum rental period?
    Q-16  How are part-day rentals calculated - round up, round down, fractional?
    Q-17  How is a hire crossing a calendar month boundary handled?
    Q-18  Is the monthly rate a cap on any period of one month or less?

No answer to any of these is inferred, defaulted or guessed. Every function that
would need one raises PricingPolicyNotConfigured until the policy is recorded in
Asset Leasing Settings. The signatures below already carry the parameters those
policies require, so implementing them later changes function bodies only - no
schema change and no caller change.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_datetime

SETTINGS = "Asset Leasing Settings"

# Each unresolved policy field, with the question it answers. Used to build an
# error message that tells the reader exactly what is missing and why.
UNRESOLVED_POLICY = {
	"proration_divisor_policy": "Q-14 - divide the monthly rate by a fixed 30, or by the actual days in the calendar month?",
	"has_minimum_rental_period": "Q-15 - is there a minimum rental period?",
	"part_day_policy": "Q-16 - how is a part day calculated?",
	"month_boundary_policy": "Q-17 - how is a hire crossing a calendar month handled?",
	"cap_at_monthly_rate": "Q-18 - is the monthly rate a cap for a period of one month or less?",
}


class PricingPolicyNotConfigured(frappe.ValidationError):
	"""Raised when a calculation needs a policy decision that nobody has made."""


# --------------------------------------------------------------- policy access
def get_policy():
	"""Return the confirmed pro-rata policy, or refuse.

	Refusing is the point. Returning a plausible default here would silently put
	an invented divisor onto a customer invoice, which is the specific failure
	this design exists to prevent.
	"""
	settings = frappe.get_cached_doc(SETTINGS)

	if not settings.pricing_policy_confirmed:
		frappe.throw(
			_("Pro-rata pricing policy is not confirmed yet.<br><br>"
			  "The monthly rate is agreed, but these decisions are outstanding:<br>{0}<br><br>"
			  "Record them in {1} and tick <b>Pricing Policy Confirmed</b>.").format(
				"<br>".join(f"&bull; {q}" for q in UNRESOLVED_POLICY.values()), SETTINGS
			),
			exc=PricingPolicyNotConfigured,
			title=_("Pricing Policy Not Confirmed"),
		)

	missing = [q for f, q in UNRESOLVED_POLICY.items() if not settings.get(f)]
	if missing:
		frappe.throw(
			_("Pricing policy is marked confirmed but these values are unset:<br>{0}").format(
				"<br>".join(f"&bull; {q}" for q in missing)
			),
			exc=PricingPolicyNotConfigured,
			title=_("Pricing Policy Incomplete"),
		)

	return settings


# ------------------------------------------------------------- implemented now
def elapsed_days(start_datetime, end_datetime):
	"""Raw elapsed duration in days as a float. Policy-free.

	No rounding, no minimum, no cap - those are Q-15, Q-16 and Q-18. This is the
	arithmetic every policy builds on, so it is safe to implement and test today.
	"""
	start, end = get_datetime(start_datetime), get_datetime(end_datetime)
	if end < start:
		frappe.throw(_("End {0} is before start {1}.").format(end, start))
	return flt((end - start).total_seconds() / 86400.0, 6)


def get_monthly_rate(rental_item, customer=None, company=None):
	"""The single source rate: Item Price on the monthly rental price list.

	Standard ERPNext pricing applies on top - Pricing Rule, customer price lists.
	Nothing here derives or adjusts; this returns the agreed monthly figure only.
	"""
	settings = frappe.get_cached_doc(SETTINGS)
	price_list = settings.monthly_price_list
	if not price_list:
		frappe.throw(_("Set <b>Monthly Price List</b> in {0}.").format(SETTINGS))

	rate = frappe.db.get_value(
		"Item Price",
		{"item_code": rental_item, "price_list": price_list, "selling": 1},
		"price_list_rate",
	)
	if rate is None:
		frappe.throw(
			_("No Item Price for {0} in price list {1}. "
			  "Rental would be billed at zero.").format(rental_item, price_list)
		)
	return flt(rate)


def apply_overdue_surcharge(daily_rate, days_overdue):
	"""Uplift the daily rate for days past expected return plus grace."""
	settings = frappe.get_cached_doc(SETTINGS)
	if flt(days_overdue) <= 0:
		return 0.0
	pct = flt(settings.overdue_surcharge_percent)
	return flt(daily_rate) * flt(days_overdue) * (1 + pct / 100.0)


# ------------------------------------------- blocked on unresolved policy
def derive_daily_rate(monthly_rate, period_start=None, period_end=None):
	"""Daily rate derived from the monthly rate.

	period_start and period_end are in the signature deliberately: under the
	actual-days divisor (Q-14) the result depends on which calendar month the
	hire falls in, so callers must already be passing the period. Implementing
	Q-14 later becomes a change to this body alone.
	"""
	get_policy()  # raises until Q-14 is answered
	raise NotImplementedError(
		"derive_daily_rate is intentionally unimplemented pending Q-14."
	)


def compute_billable_days(start_datetime, end_datetime, creditable_downtime_days=0):
	"""Billable days: elapsed, less approved downtime, then rounding and minimum.

	The elapsed and downtime arithmetic is settled; the rounding (Q-16) and the
	minimum period (Q-15) are not, so the whole function is gated.
	"""
	get_policy()  # raises until Q-15 and Q-16 are answered
	raise NotImplementedError(
		"compute_billable_days is intentionally unimplemented pending Q-15 and Q-16."
	)


def compute_line_amount(monthly_rate, start_datetime, end_datetime, creditable_downtime_days=0):
	"""Final chargeable amount for one hire line."""
	get_policy()  # raises until Q-14 to Q-18 are answered
	raise NotImplementedError(
		"compute_line_amount is intentionally unimplemented pending Q-14 to Q-18."
	)
