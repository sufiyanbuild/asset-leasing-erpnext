"""P0 installation.

Creates configuration only. No demo data, no sample records, no master data
beyond the single price list - an app that seeds records on install is unusable
on a client production site.
"""

import frappe

from asset_leasing.setup.price_list import MONTHLY_PRICE_LIST, create_price_list
from asset_leasing.setup.permissions import setup_permissions
from asset_leasing.setup.roles import create_roles


def after_install():
	roles = create_roles()
	price_list = create_price_list()
	seed_settings()
	setup_permissions()
	frappe.db.commit()

	print(f"Asset Leasing installed. Roles created: {len(roles)}. "
		  f"Price list: {price_list or MONTHLY_PRICE_LIST + ' (already present)'}.")
	print("Pro-rata pricing policy is deliberately unconfirmed - see Asset Leasing Settings (Q-14 to Q-18).")


def seed_settings():
	"""Point Settings at the monthly price list and nothing else.

	Every pro-rata policy field is left unset on purpose. pricing_policy_confirmed
	stays 0 so the pricing engine refuses to calculate rather than assuming.
	"""
	settings = frappe.get_single("Asset Leasing Settings")
	if not settings.monthly_price_list and frappe.db.exists("Price List", MONTHLY_PRICE_LIST):
		settings.monthly_price_list = MONTHLY_PRICE_LIST
	settings.pricing_policy_confirmed = 0
	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)


def after_migrate():
	"""Re-apply the configuration layer idempotently on every migrate.

	Permissions are re-applied here rather than shipped as a Custom DocPerm
	fixture: add_permission() copies the standard DocPerm rows in before adding
	ours, which a fixture import would not do.
	"""
	from asset_leasing.setup.custom_fields import create_al_custom_fields

	create_al_custom_fields()
	setup_permissions()
