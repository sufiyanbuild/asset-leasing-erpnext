"""Helpers available in print formats."""

from frappe import _
from frappe.utils import flt


def al_duration(days):
	"""'3 days' / '2 days 5 hours' for a day count."""
	if days is None:
		return ""
	whole = int(flt(days))
	hours = int(round((flt(days) - whole) * 24))
	if hours == 24:
		whole, hours = whole + 1, 0
	parts = []
	if whole:
		parts.append(_("{0} day").format(whole) if whole == 1 else _("{0} days").format(whole))
	if hours:
		parts.append(_("{0} hour").format(hours) if hours == 1 else _("{0} hours").format(hours))
	return " ".join(parts) or _("0 days")


CONDITION_ORDER = ["Excellent", "Good", "Fair", "Poor", "Damaged"]


def al_condition_changed(condition_out, condition_in):
	"""True when a machine came back in worse condition than it left."""
	if not (condition_out and condition_in):
		return False
	try:
		return CONDITION_ORDER.index(condition_in) > CONDITION_ORDER.index(condition_out)
	except ValueError:
		return condition_in != condition_out


def al_pricing_basis(agreement_type):
	"""The sentence printed on an agreement explaining how rent is charged.

	Worded from the policy recorded in Asset Leasing Settings, so the document
	a customer signs always matches what the system will bill.
	"""
	import frappe

	if agreement_type == "Long Term Contract":
		return _("Rent is invoiced monthly in advance at the monthly rate for each billing period of the contract.")

	settings = frappe.get_cached_doc("Asset Leasing Settings")
	if not settings.pricing_policy_confirmed:
		return ""

	parts = [_("Rent is charged from dispatch to return.")]
	if settings.proration_divisor_policy == "Fixed 30 Days":
		parts.append(_("The daily rate is the monthly rate divided by 30."))
	elif settings.month_boundary_policy == "Split At Month End":
		parts.append(_("Each day is charged at the monthly rate divided by the number of days in its own month."))
	else:
		parts.append(_("The daily rate is the monthly rate divided by the number of days in the month in which "
					   "the hire starts, and that rate applies to the whole hire."))
	parts.append({
		"Round Up": _("Any part of a day is charged as a full day."),
		"Round Down": _("A part day is not charged."),
		"Fractional": _("Part days are charged proportionally."),
	}.get(settings.part_day_policy, ""))
	if settings.has_minimum_rental_period == "Yes" and settings.minimum_billable_days:
		parts.append(_("A minimum of {0} days is charged.").format(settings.minimum_billable_days))
	else:
		parts.append(_("There is no minimum hire period."))
	if settings.cap_at_monthly_rate == "Yes":
		parts.append(_("A hire of one month or less is never charged more than the monthly rate."))
	parts.append(_("Transport, damage and the security deposit are settled separately."))
	return " ".join(p for p in parts if p)
