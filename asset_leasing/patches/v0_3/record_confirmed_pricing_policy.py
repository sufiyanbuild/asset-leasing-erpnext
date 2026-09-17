"""Record the client's pro-rata policy (Q-14 to Q-18, confirmed 17 Sep 2026).

Only fills an empty policy; a site that already has one recorded keeps it.
"""

import frappe

from asset_leasing.setup.install import record_confirmed_policy


def execute():
	frappe.reload_doc("asset_leasing", "doctype", "asset_leasing_settings")
	settings = frappe.get_single("Asset Leasing Settings")
	if record_confirmed_policy(settings):
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)
		print("asset_leasing: confirmed pro-rata policy recorded.")
