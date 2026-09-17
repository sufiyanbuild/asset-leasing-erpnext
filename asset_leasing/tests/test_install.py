"""T-12 - what installing the app provides, and that re-running setup changes nothing."""

import frappe
from frappe.tests import IntegrationTestCase

from asset_leasing.rental.pricing import CONFIRMED_POLICY
from asset_leasing.setup.custom_fields import CUSTOM_FIELDS, create_al_custom_fields
from asset_leasing.setup.permissions import setup_permissions
from asset_leasing.setup.roles import ROLES
from asset_leasing.setup.workflows import WORKFLOWS, create_workflow

APP_DOCTYPES = ["Rental Agreement", "Rental Dispatch", "Rental Return", "Rental Downtime Log", "Asset Leasing Settings"]


class TestInstall(IntegrationTestCase):
	def test_configuration_is_present(self):
		for role, _description in ROLES:
			self.assertTrue(frappe.db.exists("Role", role), role)
		for name in WORKFLOWS:
			self.assertEqual(frappe.db.get_value("Workflow", name, "is_active"), 1, name)
		for doctype in APP_DOCTYPES:
			self.assertTrue(frappe.db.exists("DocType", doctype), doctype)
		self.assertEqual(frappe.db.count("Notification", {"module": "Asset Leasing", "is_standard": 1}), 9)
		self.assertEqual(frappe.db.count("Report", {"module": "Asset Leasing"}), 10)
		self.assertEqual(frappe.db.count("Print Format", {"module": "Asset Leasing"}), 5)
		self.assertEqual(frappe.db.count("Number Card", {"module": "Asset Leasing"}), 8)
		self.assertEqual(frappe.db.count("Dashboard Chart", {"module": "Asset Leasing"}), 5)
		self.assertTrue(frappe.db.exists("Dashboard", "Asset Leasing Overview"))
		self.assertTrue(frappe.db.exists("Workspace", "Asset Leasing"))
		self.assertTrue(frappe.db.exists("Price List", "Rental - Monthly"))

	def test_confirmed_pricing_policy_is_recorded(self):
		settings = frappe.get_single("Asset Leasing Settings")
		self.assertTrue(settings.pricing_policy_confirmed)
		for field, value in CONFIRMED_POLICY.items():
			self.assertEqual(settings.get(field), value, field)

	def test_setup_is_idempotent(self):
		before = (
			frappe.db.count("Custom Field", {"fieldname": ["like", "al_%"]}),
			frappe.db.count("Custom DocPerm"),
			frappe.db.count("Workflow"),
			frappe.db.count("Workflow Transition"),
		)
		create_al_custom_fields()
		setup_permissions()
		create_workflow()
		after = (
			frappe.db.count("Custom Field", {"fieldname": ["like", "al_%"]}),
			frappe.db.count("Custom DocPerm"),
			frappe.db.count("Workflow"),
			frappe.db.count("Workflow Transition"),
		)
		self.assertEqual(before, after)
		self.assertEqual(before[0], sum(len(v) for v in CUSTOM_FIELDS.values()))

	def test_no_demo_or_sample_data_is_shipped(self):
		import os

		app = frappe.get_app_path("asset_leasing")
		fixtures = sorted(os.listdir(os.path.join(app, "fixtures")))
		self.assertEqual(fixtures, ["custom_field.json", "role.json", "workflow.json",
									"workflow_action_master.json", "workflow_state.json"])

	def test_print_formats_render(self):
		for name in frappe.get_all("Print Format", filters={"module": "Asset Leasing"}, pluck="name"):
			html = frappe.db.get_value("Print Format", name, "html")
			self.assertIn("add_header", html, name)
