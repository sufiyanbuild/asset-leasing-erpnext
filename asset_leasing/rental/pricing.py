"""Pricing for equipment hire.

Confirmed business rules
------------------------

Q-01  A fixed monthly rate is the only commercial rental rate (INR 45,000 per
      month for the Excavator EX-200). Hires shorter than a month are billed pro
      rata from it. Not a tiered model: no daily or weekly price lists, no
      duration bands, no tier engine.

Pro-rata policy, confirmed by the client on 17 Sep 2026 and recorded in Asset
Leasing Settings (CONFIRMED_POLICY below is what the app seeds):

Q-14  Divisor: the actual number of days in the calendar month.
Q-15  No minimum rental period. Logistics, damage and the security deposit are
      compensated separately (their own invoices and payments) and are never
      part of a rental-period charge.
Q-16  Round up: any part of a day is a full additional rental day.
Q-17  One divisor for the whole hire - the hire is not split at month ends. With
      the actual-days divisor, the one divisor is the day count of the calendar
      month in which the billed period starts.
Q-18  No cap: the prorated amount for a month or less may exceed the monthly rate.

Every calculation reads the recorded settings, not these notes, and refuses
(PricingPolicyNotConfigured) while the policy is not confirmed. The other
recorded options (fixed 30, round down, fractional, a minimum, month splitting,
a cap) are implemented too, so a changed decision is a settings change.

Arithmetic is done in whole seconds so that a hire of exactly N days is never
pushed to N+1 by floating-point noise.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, flt, get_datetime, get_first_day, get_last_day, getdate

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


# The client's answers, as Asset Leasing Settings values.
CONFIRMED_POLICY = {
	"proration_divisor_policy": "Actual Days in Month",  # Q-14
	"has_minimum_rental_period": "No",  # Q-15
	"minimum_billable_days": 0,
	"part_day_policy": "Round Up",  # Q-16
	"month_boundary_policy": "Single Divisor For Whole Hire",  # Q-17
	# Q-18: "the prorated amount for a month or less may exceed the monthly
	# rate" - so the monthly rate is not a cap.
	"cap_at_monthly_rate": "No",
}

SECONDS_PER_DAY = 86400


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


def policy_ready():
	"""True only when every pro-rata decision is recorded and confirmed.

	A silent check for callers that must carry on either way (a return is
	still submitted while pricing is gated). get_policy() is the loud version.
	"""
	settings = frappe.get_cached_doc(SETTINGS)
	return bool(settings.pricing_policy_confirmed) and all(settings.get(f) for f in UNRESOLVED_POLICY)


def pending_policy_questions():
	settings = frappe.get_cached_doc(SETTINGS)
	if settings.pricing_policy_confirmed:
		return [q for f, q in UNRESOLVED_POLICY.items() if not settings.get(f)]
	return list(UNRESOLVED_POLICY.values())


# ------------------------------------------------------------- policy-free
def elapsed_days(start_datetime, end_datetime):
	"""Raw elapsed duration in days as a float. Policy-free.

	No rounding, no minimum, no cap - those are Q-15, Q-16 and Q-18. Recorded on
	every return so the arithmetic behind a bill can always be followed.
	"""
	start, end = get_datetime(start_datetime), get_datetime(end_datetime)
	if end < start:
		frappe.throw(_("End {0} is before start {1}.").format(end, start))
	return flt((end - start).total_seconds() / 86400.0, 6)


def get_monthly_rate(rental_item, customer=None, company=None):
	"""The single source rate: the monthly figure from the rental price list.

	With a customer and company, the rate is resolved by ERPNext's own selling
	machinery on an unsaved Quotation, so a customer-specific Item Price and any
	applicable Pricing Rule apply exactly as they would on a sales document.
	Nothing here derives a daily figure; this is the agreed monthly rate only.
	"""
	settings = frappe.get_cached_doc(SETTINGS)
	price_list = settings.monthly_price_list
	if not price_list:
		frappe.throw(_("Set <b>Monthly Price List</b> in {0}.").format(SETTINGS))

	base = frappe.db.get_value(
		"Item Price",
		{"item_code": rental_item, "price_list": price_list, "selling": 1},
		"price_list_rate",
	)
	if base is None and not (customer and frappe.db.exists(
		"Item Price", {"item_code": rental_item, "price_list": price_list, "customer": customer}
	)):
		frappe.throw(
			_("No Item Price for {0} in price list {1}. "
			  "Rental would be billed at zero.").format(rental_item, price_list)
		)

	if not (customer and company):
		return flt(base)
	return _rate_through_selling_rules(rental_item, customer, company, price_list)


def _rate_through_selling_rules(item_code, customer, company, price_list):
	quotation = frappe.get_doc({
		"doctype": "Quotation",
		"quotation_to": "Customer",
		"party_name": customer,
		"company": company,
		"selling_price_list": price_list,
		"transaction_date": frappe.utils.nowdate(),
		"items": [{"item_code": item_code, "qty": 1}],
	})
	quotation.set_missing_values()
	quotation.calculate_taxes_and_totals()
	return flt(quotation.items[0].rate)


# ------------------------------------------------------------ calculations
def _seconds(start_datetime, end_datetime):
	start, end = get_datetime(start_datetime), get_datetime(end_datetime)
	if end < start:
		frappe.throw(_("End {0} is before start {1}.").format(end, start))
	return int(round((end - start).total_seconds()))


def days_in_month(date):
	return getdate(get_last_day(date)).day


def derive_daily_rate(monthly_rate, period_start=None, period_end=None):
	"""Daily rate derived from the monthly rate (Q-14).

	Actual-days: the monthly rate over the day count of the month in which the
	period starts. Unrounded; amounts are rounded once, at the end.
	"""
	return flt(monthly_rate) / divisor_for(period_start)


def divisor_for(period_start=None):
	policy = get_policy()
	if policy.proration_divisor_policy == "Fixed 30 Days":
		return 30
	if not period_start:
		frappe.throw(_("The actual-days divisor needs the date the hire period starts."))
	return days_in_month(period_start)


def compute_billable_days(start_datetime, end_datetime, creditable_downtime_days=0, adjustment_days=0):
	"""Elapsed time, less approved downtime and adjustments, rounded (Q-16),
	then floored at the minimum period (Q-15)."""
	policy = get_policy()
	net = _seconds(start_datetime, end_datetime)
	net -= int(round(flt(creditable_downtime_days) * SECONDS_PER_DAY))
	net -= int(round(flt(adjustment_days) * SECONDS_PER_DAY))
	net = max(net, 0)

	if policy.part_day_policy == "Round Up":
		days = float(-(-net // SECONDS_PER_DAY))
	elif policy.part_day_policy == "Round Down":
		days = float(net // SECONDS_PER_DAY)
	else:
		days = flt(net / SECONDS_PER_DAY, 6)

	if policy.has_minimum_rental_period == "Yes" and days < flt(policy.minimum_billable_days):
		days = flt(policy.minimum_billable_days)
	return days


def price_hire(monthly_rate, start_datetime, end_datetime, creditable_downtime_days=0, adjustment_days=0):
	"""The full calculation for one machine, with its working shown."""
	policy = get_policy()
	days = compute_billable_days(start_datetime, end_datetime, creditable_downtime_days, adjustment_days)
	start_date = getdate(get_datetime(start_datetime))
	monthly = flt(monthly_rate)

	segments = []
	if policy.proration_divisor_policy == "Actual Days in Month" and policy.month_boundary_policy == "Split At Month End":
		segments = _split_by_month(monthly, start_date, days)
	else:
		divisor = divisor_for(start_date)
		segments = [{"from": start_date, "days": days, "divisor": divisor, "amount": monthly * days / divisor}]

	amount = sum(seg["amount"] for seg in segments)
	if policy.cap_at_monthly_rate == "Yes":
		amount = _apply_cap(monthly, get_datetime(start_datetime), days, segments[0]["divisor"], amount)

	first_divisor = segments[0]["divisor"] if segments else divisor_for(start_date)
	return frappe._dict(
		billable_days=days,
		divisor=first_divisor,
		daily_rate=flt(monthly / first_divisor, 2),
		amount=flt(amount, 2),
		segments=[{**seg, "amount": flt(seg["amount"], 2)} for seg in segments],
	)


def _split_by_month(monthly, start_date, days):
	"""Charge each billable day at the rate of the month it falls in."""
	segments, remaining, cursor = [], days, start_date
	while remaining > 0:
		month_left = (getdate(get_last_day(cursor)) - cursor).days + 1
		take = min(remaining, month_left)
		divisor = days_in_month(cursor)
		segments.append({"from": cursor, "days": take, "divisor": divisor, "amount": monthly * take / divisor})
		remaining -= take
		cursor = getdate(get_first_day(add_months(cursor, 1)))
	return segments or [{"from": start_date, "days": 0, "divisor": days_in_month(start_date), "amount": 0.0}]


def _apply_cap(monthly, start, days, divisor, amount):
	"""A period of one calendar month or less never exceeds the monthly rate;
	longer periods are whole calendar months at the monthly rate plus the
	remainder, itself capped."""
	from datetime import timedelta

	end = start + timedelta(days=days)
	months = 0
	while get_datetime(add_months(start, months + 1)) <= end:
		months += 1
	if not months:
		return min(amount, monthly)
	remainder = (end - get_datetime(add_months(start, months))).total_seconds() / SECONDS_PER_DAY
	return monthly * months + min(monthly, monthly * remainder / divisor)


def compute_line_amount(monthly_rate, start_datetime, end_datetime, creditable_downtime_days=0, adjustment_days=0):
	"""Final chargeable rent for one hire line (Q-14 to Q-18)."""
	return price_hire(monthly_rate, start_datetime, end_datetime, creditable_downtime_days, adjustment_days).amount


def estimate_period_amount(monthly_rate, start_date, end_date):
	"""Rent for an agreed period of whole calendar days, start to end inclusive."""
	start = get_datetime(getdate(start_date))
	end = get_datetime(add_days(getdate(end_date), 1))
	return price_hire(monthly_rate, start, end)


def overdue_days(expected_end_date, return_datetime):
	"""Days a return runs past the expected end date plus the grace days (10.7)."""
	if not expected_end_date:
		return 0.0
	grace = int(frappe.get_cached_doc(SETTINGS).overdue_grace_days or 0)
	due = get_datetime(add_days(getdate(expected_end_date), 1 + grace))
	if get_datetime(return_datetime) <= due:
		return 0.0
	return compute_billable_days(due, return_datetime)


def overdue_surcharge(daily_rate, days):
	"""The uplift on overdue days only (Q-05 working default: 0%).

	The overdue days are already in the rental line at the normal daily rate;
	this is the extra percentage, billed on its own line so it can be seen.
	"""
	pct = flt(frappe.get_cached_doc(SETTINGS).overdue_surcharge_percent)
	if flt(days) <= 0 or pct <= 0:
		return 0.0
	return flt(flt(daily_rate) * flt(days) * pct / 100.0, 2)
