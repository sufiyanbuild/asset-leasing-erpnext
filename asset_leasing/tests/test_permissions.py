"""T-P1-09 - role access, and proof that ERPNext's own roles survived."""

import frappe
from frappe.tests import IntegrationTestCase

from asset_leasing.setup.permissions import PERMISSIONS, PERMLEVEL_1


class TestLeasingPermissions(IntegrationTestCase):
	def test_all_six_roles_exist(self):
		roles = frappe.get_all("Role", filters={"role_name": ["like", "Leasing %"]}, pluck="name")
		self.assertEqual(len(roles), 6, f"expected 6 leasing roles, found {sorted(roles)}")

	def test_declared_permissions_applied(self):
		missing = []
		for doctype, roles in PERMISSIONS.items():
			for role, ptypes in roles.items():
				row = frappe.db.get_value(
					"Custom DocPerm",
					{"parent": doctype, "role": role, "permlevel": 0},
					["read", "write", "create", "submit", "cancel", "amend", "delete"],
					as_dict=True,
				)
				if not row:
					missing.append(f"{doctype}/{role}")
					continue
				for ptype, expected in ptypes.items():
					if row.get(ptype) != expected:
						missing.append(f"{doctype}/{role}.{ptype}={row.get(ptype)} expected {expected}")
		self.assertEqual(missing, [])

	def test_erpnext_roles_preserved_on_shared_doctypes(self):
		"""Custom DocPerm replaces standard DocPerm entirely for a DocType.

		add_permission() copies the standard rows in first. If that ever stops
		happening, ERPNext's own roles lose access and this test catches it.
		"""
		for doctype, must_keep in [
			("Sales Invoice", ["Accounts Manager", "Accounts User"]),
			("Customer", ["Sales User"]),
			("Item", ["Item Manager"]),
		]:
			roles = frappe.get_all("Custom DocPerm", filters={"parent": doctype}, pluck="role")
			for role in must_keep:
				self.assertIn(role, roles, f"{role} lost access to {doctype}")

	def test_commercial_fields_restricted_to_permlevel_1(self):
		for doctype in PERMLEVEL_1:
			rows = frappe.get_all(
				"Custom DocPerm", filters={"parent": doctype, "permlevel": 1}, pluck="role"
			)
			self.assertNotIn("Leasing Yard Supervisor", rows)
			self.assertNotIn("Leasing Maintenance Technician", rows)
			self.assertIn("Leasing Manager", rows)

	def test_no_leasing_role_can_delete_assets(self):
		for role in ["Leasing Hire Desk", "Leasing Yard Supervisor", "Leasing Maintenance Technician"]:
			deletable = frappe.db.get_value(
				"Custom DocPerm", {"parent": "Asset", "role": role, "permlevel": 0}, "delete"
			)
			self.assertFalse(deletable, f"{role} must not delete Assets")
