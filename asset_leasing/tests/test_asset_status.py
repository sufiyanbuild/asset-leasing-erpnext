"""T-P1-05, T-P1-06 - the rental status state machine."""

import frappe
from frappe.tests import IntegrationTestCase

from asset_leasing.rental import asset_status as st


class TestAssetStatusMachine(IntegrationTestCase):
	def test_legal_transitions(self):
		self.assertTrue(st.can_transition(st.AVAILABLE, st.RESERVED))
		self.assertTrue(st.can_transition(st.RESERVED, st.ON_HIRE))
		self.assertTrue(st.can_transition(st.ON_HIRE, st.UNDER_INSPECTION))
		self.assertTrue(st.can_transition(st.UNDER_INSPECTION, st.UNDER_REPAIR))
		self.assertTrue(st.can_transition(st.UNDER_REPAIR, st.RETIRED))

	def test_illegal_transitions(self):
		# A machine cannot go straight from the yard to on hire without dispatch.
		self.assertFalse(st.can_transition(st.AVAILABLE, st.ON_HIRE))
		# Equipment in the field must come back before it is written off.
		self.assertFalse(st.can_transition(st.ON_HIRE, st.RETIRED))
		self.assertFalse(st.can_transition(st.RESERVED, st.RETIRED))

	def test_retired_is_terminal(self):
		for target in st.ALL_STATUSES:
			if target == st.RETIRED:
				continue
			self.assertFalse(
				st.can_transition(st.RETIRED, target), f"Retired should not reach {target}"
			)

	def test_same_status_is_a_noop(self):
		for status in st.ALL_STATUSES:
			self.assertTrue(st.can_transition(status, status))

	def test_assert_transition_raises_and_names_both_states(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			st.assert_transition(st.ON_HIRE, st.RETIRED, asset="TEST-ASSET")
		message = str(ctx.exception)
		self.assertIn("On Hire", message)
		self.assertIn("Retired", message)

	def test_out_of_yard_set(self):
		self.assertEqual(st.OUT_OF_YARD, {st.RESERVED, st.ON_HIRE, st.IN_TRANSIT})

	def test_every_status_has_a_transition_rule(self):
		for status in st.ALL_STATUSES:
			self.assertIn(status, st.ALLOWED_TRANSITIONS)
