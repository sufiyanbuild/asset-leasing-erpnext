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
