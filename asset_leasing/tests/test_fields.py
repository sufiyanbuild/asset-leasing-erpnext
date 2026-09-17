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
		self.assertEqual(total, 47)

	def test_fields_are_app_owned_not_orphaned(self):
		"""Every al_ field must be a real Custom Field record, exportable as a fixture."""
		count = frappe.db.count("Custom Field", {"fieldname": ["like", "al_%"]})
		expected = sum(len(v) for v in CUSTOM_FIELDS.values())
		self.assertEqual(count, expected)

	def test_patch_is_idempotent(self):
		"""Re-running the field patch must change nothing."""
		from asset_leasing.setup.custom_fields import create_al_custom_fields

		before = frappe.db.count("Custom Field", {"fieldname": ["like", "al_%"]})
		create_al_custom_fields()
		after = frappe.db.count("Custom Field", {"fieldname": ["like", "al_%"]})
		self.assertEqual(before, after)

	def test_rental_document_links_present(self):
		"""Every link to an app DocType exists now that all its targets do."""
		for doctype, fieldname in [
			("Asset", "al_current_agreement"),
			("Sales Invoice", "al_rental_agreement"),
			("Sales Invoice", "al_rental_dispatch"),
			("Sales Invoice", "al_rental_return"),
			("Asset Repair", "al_rental_return"),
			("Subscription", "al_rental_agreement"),
			("Payment Entry", "al_rental_agreement"),
			("Payment Entry", "al_deposit_type"),
			("Asset", "al_compliance_status"),
		]:
			self.assertTrue(frappe.get_meta(doctype).has_field(fieldname), f"{doctype}.{fieldname}")

	def test_every_field_ships_in_the_fixture(self):
		import json
		import os

		path = os.path.join(frappe.get_app_path("asset_leasing"), "fixtures", "custom_field.json")
		shipped = {(d["dt"], d["fieldname"]) for d in json.load(open(path))}
		defined = {(dt, f["fieldname"]) for dt, fields in CUSTOM_FIELDS.items() for f in fields}
		self.assertEqual(defined - shipped, set())
