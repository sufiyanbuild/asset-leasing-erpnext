"""Installation.

Creates configuration only. No demo data, no sample records, no master data
beyond the single price list - an app that seeds records on install is unusable
on a client production site. The client's confirmed pro-rata policy is
configuration, so it is recorded.
"""

import frappe

from asset_leasing.setup.price_list import MONTHLY_PRICE_LIST, create_price_list
from asset_leasing.setup.permissions import setup_permissions
from asset_leasing.setup.roles import create_roles
from asset_leasing.setup.workflows import create_workflow


def after_install():
	roles = create_roles()
	price_list = create_price_list()
	seed_settings()
	setup_permissions()
	create_workflow()
	frappe.db.commit()

	print(f"Asset Leasing installed. Roles created: {len(roles)}. "
		  f"Price list: {price_list or MONTHLY_PRICE_LIST + ' (already present)'}.")
	print("Pro-rata pricing policy recorded as confirmed by the client (Q-14 to Q-18).")


def seed_settings():
	"""Point Settings at the monthly price list and record the pricing policy."""
	settings = frappe.get_single("Asset Leasing Settings")
	if not settings.monthly_price_list and frappe.db.exists("Price List", MONTHLY_PRICE_LIST):
		settings.monthly_price_list = MONTHLY_PRICE_LIST
	record_confirmed_policy(settings)
	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)


def record_confirmed_policy(settings):
	"""Write the client's Q-14 to Q-18 answers where nothing is recorded yet.

	A site on which someone has already recorded a policy keeps it: this never
	overwrites a decision, it only fills an empty policy.
	"""
	from asset_leasing.rental.pricing import CONFIRMED_POLICY, UNRESOLVED_POLICY

	if any(settings.get(field) for field in UNRESOLVED_POLICY):
		return False
	settings.update(CONFIRMED_POLICY)
	settings.pricing_policy_confirmed = 1
	return True


def after_migrate():
	"""Re-apply the configuration layer idempotently on every migrate.

	Permissions are re-applied here rather than shipped as a Custom DocPerm
	fixture: add_permission() copies the standard DocPerm rows in before adding
	ours, which a fixture import would not do.
	"""
	from asset_leasing.setup.custom_fields import create_al_custom_fields

	create_al_custom_fields()
	setup_permissions()
	create_workflow()
