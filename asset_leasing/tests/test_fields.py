"""T-P1-01 - the al_ custom field layer is installed correctly."""

import frappe
from frappe.tests import IntegrationTestCase

from asset_leasing.setup.custom_fields import CUSTOM_FIELDS


class TestALFields(IntegrationTestCase):
	def test_all_fields_exist_with_correct_shape(self):
		problems = []
		total = 0
		for doctype, fields in CUSTOM_FIELDS.items():
			meta = frappe.get_meta(doctype)
			for spec in fields:
				total += 1
				fieldname = spec["fieldname"]
				field = meta.get_field(fieldname)
				if not field:
					problems.append(f"{doctype}.{fieldname} missing")
					continue
				if field.fieldtype != spec["fieldtype"]:
					problems.append(f"{doctype}.{fieldname} is {field.fieldtype}, expected {spec['fieldtype']}")
				if spec.get("options") and field.options != spec["options"]:
					problems.append(f"{doctype}.{fieldname} options differ")
				if spec.get("read_only") and not field.read_only:
					problems.append(f"{doctype}.{fieldname} should be read_only")
				if spec.get("permlevel") and field.permlevel != spec["permlevel"]:
					problems.append(f"{doctype}.{fieldname} permlevel {field.permlevel}")
		self.assertEqual(problems, [], f"{len(problems)} of {total} fields wrong")
		self.assertEqual(total, 38, "expected 38 custom fields")

	def test_fields_are_app_owned_not_orphaned(self):
		"""Every al_ field must be a real Custom Field record, exportable as a fixture."""
		count = frappe.db.count("Custom Field", {"fieldname": ["like", "al_%"]})
		self.assertEqual(count, 38)

	def test_patch_is_idempotent(self):
		"""Re-running the field patch must change nothing."""
		from asset_leasing.setup.custom_fields import create_al_custom_fields

		before = frappe.db.count("Custom Field", {"fieldname": ["like", "al_%"]})
		create_al_custom_fields()
		after = frappe.db.count("Custom Field", {"fieldname": ["like", "al_%"]})
		self.assertEqual(before, after)

	def test_deferred_link_fields_absent(self):
		"""Fields pointing at DocTypes that do not exist yet must not be here."""
		for doctype, fieldname in [
			("Asset", "al_current_agreement"),
			("Sales Invoice", "al_rental_agreement"),
			("Asset Repair", "al_rental_return"),
		]:
			self.assertFalse(
				frappe.get_meta(doctype).has_field(fieldname),
				f"{doctype}.{fieldname} should be deferred until its target DocType exists",
			)
