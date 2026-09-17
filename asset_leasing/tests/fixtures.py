"""Minimal master data for tests.

leasing.local has not been through the ERPNext setup wizard, so it has no Item
Group, UOM, Customer Group or Territory. Choosing a company name, country and
fiscal year is a business decision, so the wizard is deliberately not run.

These helpers build only what a test needs. IntegrationTestCase rolls back, so
nothing persists on the site.
"""

import frappe

PREFIX = "_AL Test"


def _ensure_tree_root(doctype, name_field, name, extra=None):
	if frappe.db.exists(doctype, name):
		return name
	doc = frappe.get_doc({"doctype": doctype, name_field: name, "is_group": 1, **(extra or {})})
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return name


def ensure_item_group():
	root = _ensure_tree_root("Item Group", "item_group_name", f"{PREFIX} Root Group")
	child = f"{PREFIX} Group"
	if not frappe.db.exists("Item Group", child):
		frappe.get_doc({
			"doctype": "Item Group", "item_group_name": child,
			"parent_item_group": root, "is_group": 0,
		}).insert(ignore_permissions=True)
	return child


def ensure_uom():
	name = f"{PREFIX} Unit"
	if not frappe.db.exists("UOM", name):
		frappe.get_doc({"doctype": "UOM", "uom_name": name, "must_be_whole_number": 0}).insert(
			ignore_permissions=True
		)
	return name


def ensure_customer_group():
	root = _ensure_tree_root("Customer Group", "customer_group_name", f"{PREFIX} Root CG")
	child = f"{PREFIX} CG"
	if not frappe.db.exists("Customer Group", child):
		frappe.get_doc({
			"doctype": "Customer Group", "customer_group_name": child,
			"parent_customer_group": root, "is_group": 0,
		}).insert(ignore_permissions=True)
	return child


def ensure_territory():
	root = _ensure_tree_root("Territory", "territory_name", f"{PREFIX} Root Terr")
	child = f"{PREFIX} Terr"
	if not frappe.db.exists("Territory", child):
		frappe.get_doc({
			"doctype": "Territory", "territory_name": child,
			"parent_territory": root, "is_group": 0,
		}).insert(ignore_permissions=True)
	return child


def ensure_asset_category():
	"""ERPNext requires an Asset Category on any fixed-asset Item.

	Asset Category.validate only iterates its accounts and finance_books child
	tables, so one with neither inserts cleanly and needs no Company.
	"""
	name = f"{PREFIX} Asset Category"
	if not frappe.db.exists("Asset Category", name):
		doc = frappe.get_doc({"doctype": "Asset Category", "asset_category_name": name})
		# The accounts child table is reqd at DocType level and needs a Company
		# with a chart of accounts. Asset Category is not what these tests cover,
		# so the requirement is skipped rather than building a whole company.
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
	return name


def make_item(code, is_fixed_asset=0, is_rental_item=0):
	if frappe.db.exists("Item", code):
		return code
	payload = {
		"doctype": "Item", "item_code": code, "item_name": code,
		"item_group": ensure_item_group(), "stock_uom": ensure_uom(),
		"is_stock_item": 0, "is_fixed_asset": is_fixed_asset,
		"al_is_rental_item": is_rental_item,
	}
	if is_fixed_asset:
		payload["asset_category"] = ensure_asset_category()
	frappe.get_doc(payload).insert(ignore_permissions=True)
	return code


def make_location(name, location_type="Owned Yard"):
	if frappe.db.exists("Location", name):
		return name
	frappe.get_doc({
		"doctype": "Location", "location_name": name, "al_location_type": location_type,
	}).insert(ignore_permissions=True)
	return name


def make_customer(name, blocked=False):
	if frappe.db.exists("Customer", name):
		return name
	frappe.get_doc({
		"doctype": "Customer", "customer_name": name,
		"customer_group": ensure_customer_group(), "territory": ensure_territory(),
		"al_hire_blocked": 1 if blocked else 0,
		"al_hire_block_reason": "Test block" if blocked else None,
	}).insert(ignore_permissions=True)
	return name


# ---------------------------------------------------------------- P2 fixtures
def ensure_company():
	"""A minimal company with a chart of accounts.

	Rental Agreements need one. Creating a Company is slow but unavoidable for
	genuine integration coverage, and the test runner rolls it back.
	"""
	name = f"{PREFIX} Co"
	if frappe.db.exists("Company", name):
		return name
	ensure_fiscal_year()
	# Company.on_update creates a transit warehouse; the setup wizard normally
	# supplies its Warehouse Type.
	if not frappe.db.exists("Warehouse Type", "Transit"):
		frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(ignore_permissions=True)
	frappe.get_doc({
		"doctype": "Company",
		"company_name": name,
		"abbr": "ALTC",
		"default_currency": "INR",
		"country": "India",
	}).insert(ignore_permissions=True)
	return name


def ensure_fiscal_year():
	"""Invoices need a fiscal year covering the posting date; a bare site has none."""
	from frappe.utils import getdate, nowdate

	today = getdate(nowdate())
	covered = frappe.db.sql(
		"select name from `tabFiscal Year` where %s between year_start_date and year_end_date and disabled = 0",
		today,
	)
	if covered:
		return covered[0][0]
	start = today.replace(month=4, day=1) if today.month >= 4 else today.replace(year=today.year - 1, month=4, day=1)
	end = start.replace(year=start.year + 1, month=3, day=31)
	fy = frappe.get_doc({
		"doctype": "Fiscal Year", "year": f"{PREFIX} FY {start.year}",
		"year_start_date": start, "year_end_date": end,
	})
	fy.insert(ignore_permissions=True)
	return fy.name


def ensure_asset_category_with_accounts(company):
	"""Asset Category needs accounts tied to a company before an Asset can submit."""
	name = f"{PREFIX} Plant"
	if frappe.db.exists("Asset Category", name):
		return name

	def acc(account_type=None, root=None, like=None):
		filters = {"company": company, "is_group": 0}
		if account_type:
			filters["account_type"] = account_type
		if root:
			filters["root_type"] = root
		found = frappe.db.get_value("Account", filters, "name")
		if found:
			return found
		if like:
			return frappe.db.get_value(
				"Account", {"company": company, "is_group": 0, "account_name": ["like", like]}, "name"
			)
		return None

	fixed = acc(account_type="Fixed Asset") or acc(root="Asset")
	depr_accum = acc(account_type="Accumulated Depreciation") or fixed
	depr_exp = acc(account_type="Depreciation") or acc(root="Expense")

	frappe.get_doc({
		"doctype": "Asset Category",
		"asset_category_name": name,
		"accounts": [{
			"company_name": company,
			"fixed_asset_account": fixed,
			"accumulated_depreciation_account": depr_accum,
			"depreciation_expense_account": depr_exp,
		}],
	}).insert(ignore_permissions=True)
	return name


def make_rentable_asset(asset_name, company=None, rental_item=None, yard=None, rate=45000):
	"""A submitted, rentable Asset - the thing a hire agreement commits."""
	if frappe.db.exists("Asset", {"asset_name": asset_name}):
		return frappe.db.get_value("Asset", {"asset_name": asset_name}, "name")

	company = company or ensure_company()
	category = ensure_asset_category_with_accounts(company)
	yard = yard or make_location(f"{PREFIX} Yard", "Owned Yard")

	capital_item = f"{PREFIX} Machine {asset_name}"
	if not frappe.db.exists("Item", capital_item):
		frappe.get_doc({
			"doctype": "Item", "item_code": capital_item, "item_name": capital_item,
			"item_group": ensure_item_group(), "stock_uom": ensure_uom(),
			"is_stock_item": 0, "is_fixed_asset": 1, "asset_category": category,
		}).insert(ignore_permissions=True)

	rental_item = rental_item or make_rental_charge_item(f"{PREFIX} Hire {asset_name}", rate)

	asset = frappe.get_doc({
		"doctype": "Asset",
		"asset_name": asset_name,
		"item_code": capital_item,
		"asset_category": category,
		"company": company,
		"location": yard,
		"asset_type": "Existing Asset",
		"purchase_date": "2026-01-01",
		"available_for_use_date": "2026-01-01",
		"purchase_amount": 3500000,
		"net_purchase_amount": 3500000,
		"total_asset_cost": 3500000,
		"asset_quantity": 1,
		"calculate_depreciation": 0,
		"al_is_rentable": 1,
		"al_rental_item": rental_item,
		"al_base_location": yard,
	})
	asset.flags.ignore_mandatory = True
	asset.insert(ignore_permissions=True)
	asset.submit()
	return asset.name


def make_rental_charge_item(code, rate=45000):
	"""A non-stock service item with a price on the monthly rental price list."""
	make_item(code, is_fixed_asset=0, is_rental_item=1)
	price_list = frappe.db.get_value("Asset Leasing Settings", None, "monthly_price_list") \
		or "Rental - Monthly"
	if frappe.db.exists("Price List", price_list) and not frappe.db.exists(
		"Item Price", {"item_code": code, "price_list": price_list}
	):
		frappe.get_doc({
			"doctype": "Item Price", "item_code": code, "price_list": price_list,
			"selling": 1, "price_list_rate": rate,
		}).insert(ignore_permissions=True)
	return code


def make_agreement(customer, asset, start_date, end_date=None, open_ended=False,
				   company=None, site=None, submit=False, **kwargs):
	"""Build a Rental Agreement. submit=True pushes it through the workflow."""
	company = company or ensure_company()
	site = site or make_location(f"{PREFIX} Site", "Customer Site")

	doc = frappe.get_doc({
		"doctype": "Rental Agreement",
		"customer": customer,
		"company": company,
		"agreement_type": "Short Term Hire",
		"hire_type": "Dry Hire",
		"start_date": start_date,
		"is_open_ended": 1 if open_ended else 0,
		"expected_end_date": None if open_ended else end_date,
		"site_location": site,
		"items": [{"asset": asset}],
		**kwargs,
	})
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	if submit:
		doc.submit()
		doc.reload()
	return doc


# ------------------------------------------------------------- P3+ fixtures
from frappe.utils import add_days, add_to_date, now_datetime, nowdate  # noqa: E402

CONFIRMED = {
	"pricing_policy_confirmed": 1,
	"proration_divisor_policy": "Actual Days in Month",
	"has_minimum_rental_period": "No",
	"minimum_billable_days": 0,
	"part_day_policy": "Round Up",
	"month_boundary_policy": "Single Divisor For Whole Hire",
	"cap_at_monthly_rate": "No",
}


def company_abbr(company=None):
	return frappe.db.get_value("Company", company or ensure_company(), "abbr")


def make_site(name=f"{PREFIX} Site"):
	return make_location(name, "Customer Site")


def make_yard(name=f"{PREFIX} Yard"):
	return make_location(name, "Owned Yard")


def ensure_deposit_account(company=None):
	"""A plain Liability ledger (no account type) for security deposits."""
	company = company or ensure_company()
	name = f"{PREFIX} Deposits - {company_abbr(company)}"
	if frappe.db.exists("Account", name):
		return name
	parent = frappe.db.get_value(
		"Account", {"company": company, "root_type": "Liability", "is_group": 1}, "name", order_by="lft desc"
	)
	frappe.get_doc({
		"doctype": "Account", "account_name": f"{PREFIX} Deposits", "company": company,
		"parent_account": parent, "root_type": "Liability", "is_group": 0, "account_type": "",
	}).insert(ignore_permissions=True)
	return name


def ensure_service_item(code):
	return make_item(code, is_fixed_asset=0, is_rental_item=0)


def billing_settings(company=None):
	"""Settings values that let every invoice path run in a test."""
	return {
		**CONFIRMED,
		"damage_charge_item": ensure_service_item(f"{PREFIX} Damage Recovery"),
		"transport_charge_item": ensure_service_item(f"{PREFIX} Transport"),
		"deposit_liability_account": ensure_deposit_account(company),
		"default_yard_location": make_yard(),
	}


def make_user(email, roles):
	if not frappe.db.exists("User", email):
		user = frappe.get_doc({
			"doctype": "User", "email": email, "first_name": email.split("@")[0],
			"send_welcome_email": 0, "user_type": "System User",
		})
		user.insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	user.add_roles(*roles)
	return email


def approved_agreement(customer, asset, days_ago=10, length=30, **kwargs):
	"""A submitted agreement that started days_ago and runs for length days."""
	start = add_days(nowdate(), -days_ago)
	end = None if kwargs.get("open_ended") else add_days(start, length - 1)
	return make_agreement(customer, asset, start, end, submit=True, **kwargs)


def dispatch(agreement, hours_ago=48, submit=True, **kwargs):
	agreement.reload()
	doc = frappe.get_doc({
		"doctype": "Rental Dispatch",
		"rental_agreement": agreement.name,
		"dispatch_datetime": add_to_date(now_datetime(), hours=-hours_ago),
		"from_location": kwargs.pop("from_location", make_yard()),
		"transport_mode": kwargs.pop("transport_mode", "Customer Collected"),
		"items": kwargs.pop("items", None) or [
			{"asset": row.asset, "agreement_item": row.name, "condition_out": "Good", "meter_reading_out": 100}
			for row in agreement.items if row.line_status == "Pending Dispatch"
		],
		**kwargs,
	})
	doc.insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


def return_doc(agreement, hours_ago=0, submit=True, damages=None, **kwargs):
	agreement.reload()
	items = kwargs.pop("items", None) or [
		{"asset": row.asset, "agreement_item": row.name, "condition_in": "Good",
		 "post_return_status": "Available", "meter_reading_in": 150}
		for row in agreement.items if row.line_status == "On Hire"
	]
	doc = frappe.get_doc({
		"doctype": "Rental Return",
		"rental_agreement": agreement.name,
		"return_datetime": kwargs.pop("return_datetime", add_to_date(now_datetime(), hours=-hours_ago)),
		"to_location": kwargs.pop("to_location", make_yard()),
		"inspection_result": "Damage Found" if damages else "Passed",
		"inspected_by": "Administrator",
		"items": items,
		"damages": damages or [],
		**kwargs,
	})
	doc.insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc
