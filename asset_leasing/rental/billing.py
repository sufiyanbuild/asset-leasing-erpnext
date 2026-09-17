"""Where the rental layer meets standard accounting (Section 10.5).

* Every invoice this app raises is a DRAFT Sales Invoice. Finance reviews and
  submits; nothing here posts to the ledger.
* Rent is always billed through the machine's non-stock rental charge item and
  identified by Sales Invoice Item.al_asset - never through the core `asset`
  field, which ERPNext reads as a disposal.
* Invoices point back at the rental document that caused them
  (al_rental_agreement, al_rental_dispatch, al_rental_return). The rental
  documents do not hold links to the invoices. That keeps a draft invoice
  deletable, and lets Frappe's own linked-document check refuse to cancel a
  dispatch or return once its invoice is submitted (VAL-24).
* Long-term contracts are billed by a standard ERPNext Subscription. The app
  creates and cancels it and never reimplements its scheduler.
* Short-term rent needs the pro-rata policy (Q-14 to Q-18). Until that is
  confirmed no rental amount is computed and no rental invoice is raised.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, flt, get_datetime, getdate, nowdate

from asset_leasing.rental import pricing

SETTINGS = "Asset Leasing Settings"
LONG_TERM = "Long Term Contract"
SHORT_TERM = "Short Term Hire"

PURPOSE_RENTAL = "Rental"
PURPOSE_DAMAGE = "Damage Recovery"
PURPOSE_TRANSPORT = "Transport"

AWAITING_POLICY = "Awaiting Pricing Policy"
BILLED_BY_SUBSCRIPTION = "Billed by Subscription"
INVOICED = "Invoiced"


def _settings():
	return frappe.get_cached_doc(SETTINGS)


# ------------------------------------------------------------------ invoices
def _new_invoice(agreement, purpose, **links):
	invoice = frappe.new_doc("Sales Invoice")
	invoice.company = agreement.company
	invoice.customer = agreement.customer
	invoice.currency = agreement.currency
	invoice.posting_date = nowdate()
	invoice.al_invoice_purpose = purpose
	invoice.al_rental_agreement = agreement.name
	for field, value in links.items():
		invoice.set(field, value)
	return invoice


def _add_line(invoice, item_code, rate, description, asset=None, income_account=None):
	row = invoice.append("items", {
		"item_code": item_code,
		"qty": 1,
		"rate": flt(rate),
		"price_list_rate": flt(rate),
		"description": description,
	})
	if asset:
		row.al_asset = asset
	if income_account:
		row.income_account = income_account
	return row


def _save_draft(invoice):
	"""Complete and insert the draft as a system action.

	Invoices are raised automatically when a hire document is completed, by
	whoever completed it - a yard supervisor, a technician, a manager. ERPNext
	checks Account permission while filling party accounts, which those roles
	rightly do not have, so the draft is built as Administrator and the person
	who triggered it is recorded on it. Finance still reviews and submits.
	"""
	triggered_by = frappe.session.user
	with _as_system():
		return _complete_and_insert(invoice, triggered_by)


def _complete_and_insert(invoice, triggered_by):
	wanted = [(row.rate, row.income_account, row.description) for row in invoice.items]
	note = _("Raised automatically for {0}.").format(triggered_by)
	invoice.remarks = f"{invoice.remarks}\n{note}" if invoice.get("remarks") else note
	invoice.set_missing_values()
	# set_missing_values fills item defaults; the amounts and accounts decided
	# here are not negotiable, so they are put back before totalling.
	for row, (rate, account, description) in zip(invoice.items, wanted):
		row.rate = rate
		row.price_list_rate = rate
		row.discount_percentage = 0
		row.discount_amount = 0
		row.description = description
		if account:
			row.income_account = account
	invoice.ignore_pricing_rule = 1
	invoice.calculate_taxes_and_totals()
	invoice.flags.ignore_permissions = True
	invoice.insert()
	return invoice.name


class _as_system:
	def __enter__(self):
		self.user = frappe.session.user
		if self.user != "Administrator":
			frappe.set_user("Administrator")

	def __exit__(self, *exc):
		if frappe.session.user != self.user:
			frappe.set_user(self.user)
		return False


def open_invoices(filters):
	"""Invoices matching filters that are not cancelled."""
	return frappe.get_all(
		"Sales Invoice", filters={**filters, "docstatus": ["<", 2]}, fields=["name", "docstatus"]
	)


def delete_draft_invoices(filters):
	deleted = []
	for name in frappe.get_all("Sales Invoice", filters={**filters, "docstatus": 0}, pluck="name"):
		frappe.delete_doc("Sales Invoice", name, ignore_permissions=True)
		deleted.append(name)
	return deleted


def _require_item(fieldname, what):
	item = _settings().get(fieldname)
	if not item:
		frappe.throw(
			_("Set <b>{0}</b> in {1} before raising {2} invoices.").format(
				frappe.get_meta(SETTINGS).get_label(fieldname), SETTINGS, what
			),
			title=_("Billing Item Not Configured"),
		)
	return item


# ------------------------------------------------------------ damage (AL-15)
def chargeable_damage_rows(rental_return):
	return [d for d in rental_return.damages if d.chargeable_to_customer and flt(d.estimated_cost) > 0]


def create_damage_invoice(rental_return):
	"""Draft Damage Recovery invoice for the approved chargeable damage.

	Q-07 is still open; the working default in the specification is "invoice,
	with a manual deposit offset". The offset is a normal Journal Entry made by
	Finance, so nothing here touches the deposit.
	"""
	rows = chargeable_damage_rows(rental_return)
	if not rows:
		return None
	existing = open_invoices({"al_rental_return": rental_return.name, "al_invoice_purpose": PURPOSE_DAMAGE})
	if existing:
		return existing[0].name

	item = _require_item("damage_charge_item", _("damage recovery"))
	agreement = frappe.get_doc("Rental Agreement", rental_return.rental_agreement)
	invoice = _new_invoice(agreement, PURPOSE_DAMAGE, al_rental_return=rental_return.name)
	invoice.remarks = _("Damage recovery for return {0} on agreement {1}.").format(
		rental_return.name, agreement.name
	)
	account = _settings().damage_income_account
	for row in rows:
		_add_line(
			invoice, item, row.estimated_cost,
			_("{0} damage to {1}: {2}").format(row.severity, row.asset, row.damage_description),
			asset=row.asset, income_account=account,
		)
	return _save_draft(invoice)


# --------------------------------------------------------- transport (AL-12)
def create_transport_invoice(agreement, kind, reference_doctype, reference_name):
	"""Mobilisation (kind='mobilisation', at first dispatch) or demobilisation
	(kind='demobilisation', at final return) as a draft Transport invoice."""
	field = "mobilisation_charge" if kind == "mobilisation" else "demobilisation_charge"
	amount = flt(agreement.get(field))
	if amount <= 0:
		return None

	link_field = "al_rental_dispatch" if kind == "mobilisation" else "al_rental_return"
	existing = open_invoices({
		"al_rental_agreement": agreement.name,
		"al_invoice_purpose": PURPOSE_TRANSPORT,
		link_field: ["is", "set"],
	})
	if existing:
		return existing[0].name

	item = _require_item("transport_charge_item", _("transport"))
	invoice = _new_invoice(agreement, PURPOSE_TRANSPORT, **{link_field: reference_name})
	label = _("Mobilisation") if kind == "mobilisation" else _("Demobilisation")
	_add_line(
		invoice, item, amount,
		_("{0} charge - agreement {1} ({2} {3})").format(label, agreement.name, _(reference_doctype), reference_name),
	)
	return _save_draft(invoice)


def try_create(fn, *args, context=None):
	"""Run an invoice builder; on a configuration gap, record it instead of failing.

	The physical movement of equipment must not be refused because a billing
	item has not been set up yet. The gap is written to the agreement timeline
	and the invoice can be raised later from the form.
	"""
	from frappe.utils.messages import clear_last_message

	save_point = f"al_invoice_{frappe.generate_hash(length=8)}"
	frappe.db.savepoint(save_point)
	try:
		result = fn(*args)
	except frappe.ValidationError as e:
		frappe.db.rollback(save_point=save_point)
		clear_last_message()
		if context:
			frappe.get_doc("Rental Agreement", context).add_comment(
				"Info", _("Invoice not raised automatically: {0}").format(frappe.utils.strip_html(str(e)))
			)
		frappe.msgprint(
			_("Invoice not raised automatically: {0}").format(e), indicator="orange", alert=True
		)
		return None
	frappe.db.release_savepoint(save_point)
	return result


# --------------------------------------------------- short-term rent (AL-16)
def price_return_line(rental_return, row, agreement):
	"""Rent for one returned machine, with the working shown."""
	return pricing.price_hire(
		agreement_line(agreement, row.agreement_item).monthly_rate,
		row.dispatch_datetime,
		rental_return.return_datetime,
		creditable_downtime_days=row.downtime_days,
		adjustment_days=rental_return.adjustment_days,
	)


def agreement_line(agreement, row_name):
	for line in agreement.items:
		if line.name == row_name:
			return line
	frappe.throw(_("Line {0} is not on agreement {1}.").format(row_name, agreement.name))


def create_rental_invoice(rental_return):
	"""Draft Rental invoice for a short-term return (Q-14 to Q-18 applied).

	One line per machine at its computed rent, and - only when Asset Leasing
	Settings carries an overdue surcharge percentage - a separate line for the
	surcharge, so a customer can see it (Section 10.7).
	"""
	pricing.get_policy()
	agreement = frappe.get_doc("Rental Agreement", rental_return.rental_agreement)
	if agreement.agreement_type != SHORT_TERM:
		return None
	existing = open_invoices({"al_rental_return": rental_return.name, "al_invoice_purpose": PURPOSE_RENTAL})
	if existing:
		return existing[0].name

	invoice = _new_invoice(agreement, PURPOSE_RENTAL, al_rental_return=rental_return.name)
	for row in rental_return.items:
		line = agreement_line(agreement, row.agreement_item)
		if line.is_free_of_charge:
			continue
		priced = price_return_line(rental_return, row, agreement)
		fmt = lambda v: frappe.format(get_datetime(v), "Datetime")  # noqa: E731
		item = _add_line(
			invoice, line.rental_item, priced.amount,
			_("Hire of {0} ({1}) from {2} to {3}: {4} day(s) at {5} per month / {6} days").format(
				row.asset, row.asset_name or "", fmt(row.dispatch_datetime), fmt(rental_return.return_datetime),
				frappe.format(priced.billable_days, {"fieldtype": "Float", "precision": 2}),
				frappe.format(line.monthly_rate, {"fieldtype": "Currency", "options": agreement.currency}),
				priced.divisor,
			),
			asset=row.asset,
		)
		item.al_billable_days = priced.billable_days

		if not rental_return.waive_overdue_surcharge:
			late = pricing.overdue_days(agreement.expected_end_date, rental_return.return_datetime)
			surcharge = pricing.overdue_surcharge(line.monthly_rate / priced.divisor, late)
			if surcharge:
				extra = _add_line(
					invoice, line.rental_item, surcharge,
					_("Overdue surcharge on {0}: {1} day(s) past the agreed return").format(row.asset, late),
					asset=row.asset,
				)
				extra.al_billable_days = 0

	if not invoice.items:
		return None
	invoice.from_date = getdate(min(get_datetime(r.dispatch_datetime) for r in rental_return.items))
	invoice.to_date = getdate(rental_return.return_datetime)
	return _save_draft(invoice)


def rental_billing_status(rental_return, agreement_type):
	if agreement_type == LONG_TERM:
		return BILLED_BY_SUBSCRIPTION
	if not pricing.policy_ready():
		return AWAITING_POLICY
	return None


# ------------------------------------------------- long-term (AL-08, AL-17)
def billing_periods(start_date, end_date, limit=600):
	"""Monthly periods exactly as ERPNext Subscription computes them.

	A period runs from its start to start + 1 month - 1 day, and the next one
	starts the day after (follow_calendar_months off).
	"""
	periods = []
	period_start = getdate(start_date)
	end = getdate(end_date)
	while period_start <= end and len(periods) < limit:
		period_end = getdate(add_to_date(period_start, months=1, days=-1))
		periods.append((period_start, period_end))
		period_start = getdate(add_days(period_end, 1))
	return periods


def assert_whole_month_term(start_date, end_date):
	"""A contract must end exactly on a billing-period boundary.

	The Subscription bills the full monthly rate for every period it
	generates, including a short final one. A term ending part-way through a
	period would therefore overbill the last part month, so it is refused;
	a part-month hire is a Short Term Hire, priced pro rata.
	"""
	periods = billing_periods(start_date, end_date)
	last_start, last_end = periods[-1]
	if last_end == getdate(end_date) and len(periods) >= 2:
		return len(periods)

	if len(periods) < 2:
		frappe.throw(
			_("A Long Term Contract must run for at least two monthly billing periods. "
			  "The earliest valid end date from {0} is {1}. Use a Short Term Hire for shorter periods.").format(
				frappe.format(start_date, "Date"),
				frappe.format(billing_periods(start_date, add_to_date(start_date, months=2))[1][1], "Date"),
			),
			title=_("Contract Too Short"),
		)

	previous_end = periods[-2][1]
	frappe.throw(
		_("A Long Term Contract is billed in whole monthly periods. {0} ends part-way through the "
		  "period {1} to {2}.<br><br>Choose an end date of <b>{3}</b> or <b>{2}</b>.<br><br>"
		  "The Subscription bills a full month for every period; hire any extra days as a Short Term Hire.").format(
			frappe.format(end_date, "Date"),
			frappe.format(last_start, "Date"),
			frappe.format(last_end, "Date"),
			frappe.format(previous_end, "Date"),
		),
		title=_("Contract Does Not End On A Billing Boundary"),
	)


def contract_value(agreement):
	"""Whole-month value of a long-term contract. No proration is involved."""
	periods = len(billing_periods(agreement.start_date, agreement.expected_end_date))
	return sum(flt(row.monthly_rate) for row in agreement.items if not row.is_free_of_charge) * periods


def get_or_create_plan(item_code, rate, currency):
	existing = frappe.db.get_value(
		"Subscription Plan",
		{
			"item": item_code, "price_determination": "Fixed Rate", "cost": flt(rate),
			"currency": currency, "billing_interval": "Month", "billing_interval_count": 1,
		},
		"name",
	)
	if existing:
		return existing

	plan_name = f"{item_code} - {flt(rate):g} {currency} per Month"
	if frappe.db.exists("Subscription Plan", plan_name):
		plan_name = f"{plan_name} ({frappe.generate_hash(length=5)})"
	plan = frappe.get_doc({
		"doctype": "Subscription Plan",
		"plan_name": plan_name,
		"item": item_code,
		"currency": currency,
		"price_determination": "Fixed Rate",
		"cost": flt(rate),
		"billing_interval": "Month",
		"billing_interval_count": 1,
	})
	plan.flags.ignore_permissions = True
	plan.insert()
	return plan.name


def create_subscription(agreement):
	"""One Subscription per long-term agreement, one plan row per machine."""
	if agreement.agreement_type != LONG_TERM or agreement.subscription:
		return agreement.subscription

	plans = []
	for row in agreement.items:
		if row.is_free_of_charge:
			continue
		if flt(row.monthly_rate) <= 0:
			frappe.throw(_("Row #{0}: a monthly rate is required to bill {1}.").format(row.idx, row.asset))
		plans.append({
			"plan": get_or_create_plan(row.rental_item, row.monthly_rate, agreement.currency),
			"qty": 1,
			"al_asset": row.asset,
		})
	if not plans:
		return None

	subscription = frappe.get_doc({
		"doctype": "Subscription",
		"party_type": "Customer",
		"party": agreement.customer,
		"company": agreement.company,
		"start_date": agreement.start_date,
		"end_date": agreement.expected_end_date,
		"generate_invoice_at": "Beginning of the current subscription period",
		"follow_calendar_months": 0,
		"submit_invoice": 0,
		"generate_new_invoices_past_due_date": 1,
		"al_rental_agreement": agreement.name,
		"plans": plans,
	})
	subscription.flags.ignore_permissions = True
	subscription.insert()
	agreement.db_set("subscription", subscription.name)
	return subscription.name


def cancel_subscription(agreement):
	if not agreement.subscription:
		return []
	deleted = delete_draft_invoices({"subscription": agreement.subscription})
	subscription = frappe.get_doc("Subscription", agreement.subscription)
	if subscription.status not in ("Cancelled", "Completed"):
		subscription.flags.ignore_permissions = True
		subscription.cancel_subscription()
	return deleted


def stamp_subscription_invoice(invoice):
	"""Tie a Subscription-generated invoice back to its agreement and machines.

	ERPNext emits one invoice line per plan row, in order. Rather than trusting
	position alone, each line is matched to the next unused plan row carrying
	the same item.
	"""
	if not invoice.get("subscription"):
		return
	agreement = frappe.db.get_value("Subscription", invoice.subscription, "al_rental_agreement")
	if not agreement:
		return
	if not invoice.get("al_rental_agreement"):
		invoice.al_rental_agreement = agreement
	if (invoice.get("al_invoice_purpose") or "Standard") == "Standard":
		invoice.al_invoice_purpose = PURPOSE_RENTAL

	rows = frappe.db.sql(
		"""
		select spd.al_asset, sp.item
		from `tabSubscription Plan Detail` spd
		join `tabSubscription Plan` sp on sp.name = spd.plan
		where spd.parent = %s and spd.parenttype = 'Subscription'
		order by spd.idx
		""",
		invoice.subscription,
		as_dict=True,
	)
	used = {d.al_asset for d in invoice.items if d.get("al_asset")}
	for line in invoice.items:
		if line.get("al_asset"):
			continue
		for row in rows:
			if row.al_asset and row.al_asset not in used and row.item == line.item_code:
				line.al_asset = row.al_asset
				used.add(row.al_asset)
				break


# ------------------------------------------------------------------ roll-ups
def update_agreement_billed(agreement):
	if not agreement or not frappe.db.exists("Rental Agreement", agreement):
		return
	total = frappe.db.sql(
		"select coalesce(sum(grand_total), 0) from `tabSales Invoice` where al_rental_agreement=%s and docstatus=1",
		agreement,
	)[0][0]
	frappe.db.set_value("Rental Agreement", agreement, "total_billed_amount", flt(total), update_modified=False)


def update_asset_revenue(assets):
	for asset in {a for a in assets if a}:
		total = frappe.db.sql(
			"""
			select coalesce(sum(sii.base_net_amount), 0)
			from `tabSales Invoice Item` sii
			join `tabSales Invoice` si on si.name = sii.parent
			where sii.al_asset = %s and si.docstatus = 1 and si.al_invoice_purpose = %s
			""",
			(asset, PURPOSE_RENTAL),
		)[0][0]
		frappe.db.set_value("Asset", asset, "al_lifetime_rental_revenue", flt(total), update_modified=False)


# ------------------------------------------------------- whitelisted actions
def _check_invoice_permission(doctype, name):
	frappe.has_permission("Sales Invoice", "create", throw=True)
	frappe.get_doc(doctype, name).check_permission("read")


@frappe.whitelist()
def make_damage_invoice(rental_return):
	_check_invoice_permission("Rental Return", rental_return)
	doc = frappe.get_doc("Rental Return", rental_return)
	if doc.docstatus != 1:
		frappe.throw(_("Damage can only be invoiced once the return is inspected and submitted."))
	name = create_damage_invoice(doc)
	if not name:
		frappe.throw(_("There is no chargeable damage on {0}.").format(rental_return))
	return name


@frappe.whitelist()
def make_rental_invoice(rental_return):
	_check_invoice_permission("Rental Return", rental_return)
	doc = frappe.get_doc("Rental Return", rental_return)
	if doc.docstatus != 1:
		frappe.throw(_("Rent is invoiced from a submitted return."))
	name = create_rental_invoice(doc)
	if name:
		doc.db_set("rental_billing_status", INVOICED)
	return name


@frappe.whitelist()
def make_transport_invoice(agreement, kind):
	_check_invoice_permission("Rental Agreement", agreement)
	if kind not in ("mobilisation", "demobilisation"):
		frappe.throw(_("Unknown transport charge {0}.").format(kind))
	doc = frappe.get_doc("Rental Agreement", agreement)
	if kind == "mobilisation":
		reference = frappe.get_all(
			"Rental Dispatch", filters={"rental_agreement": agreement, "docstatus": 1},
			order_by="dispatch_datetime asc", pluck="name", limit=1,
		)
		doctype = "Rental Dispatch"
	else:
		reference = frappe.get_all(
			"Rental Return", filters={"rental_agreement": agreement, "docstatus": 1, "is_final_return": 1},
			pluck="name", limit=1,
		)
		doctype = "Rental Return"
	if not reference:
		frappe.throw(
			_("Mobilisation is invoiced after the first dispatch.") if kind == "mobilisation"
			else _("Demobilisation is invoiced after the final return.")
		)
	name = create_transport_invoice(doc, kind, doctype, reference[0])
	if not name:
		frappe.throw(_("No {0} charge is recorded on {1}.").format(kind, agreement))
	return name
