"""P2 - overlap arithmetic. Pure functions, no fixtures needed."""

from frappe.tests import IntegrationTestCase

from asset_leasing.rental.availability import periods_overlap


class TestPeriodsOverlap(IntegrationTestCase):
	def test_clearly_separate_periods(self):
		self.assertFalse(periods_overlap("2026-01-01", "2026-01-31", "2026-02-01", "2026-02-28"))
		self.assertFalse(periods_overlap("2026-02-01", "2026-02-28", "2026-01-01", "2026-01-31"))

	def test_clearly_overlapping_periods(self):
		self.assertTrue(periods_overlap("2026-01-01", "2026-01-31", "2026-01-15", "2026-02-15"))
		self.assertTrue(periods_overlap("2026-01-15", "2026-02-15", "2026-01-01", "2026-01-31"))

	def test_touching_boundaries_overlap(self):
		"""A machine returned on the 31st is not free to leave again that same day."""
		self.assertTrue(periods_overlap("2026-01-01", "2026-01-31", "2026-01-31", "2026-02-10"))

	def test_one_period_inside_another(self):
		self.assertTrue(periods_overlap("2026-01-01", "2026-12-31", "2026-06-01", "2026-06-30"))
		self.assertTrue(periods_overlap("2026-06-01", "2026-06-30", "2026-01-01", "2026-12-31"))

	def test_open_ended_blocks_everything_after_its_start(self):
		"""No end date means the machine is out until it physically returns."""
		self.assertTrue(periods_overlap("2026-01-01", None, "2026-06-01", "2026-06-30"))
		self.assertTrue(periods_overlap("2026-06-01", "2026-06-30", "2026-01-01", None))

	def test_open_ended_does_not_block_earlier_periods(self):
		"""A hire starting in June cannot conflict with one that ended in March."""
		self.assertFalse(periods_overlap("2026-06-01", None, "2026-01-01", "2026-03-31"))

	def test_both_open_ended_always_overlap(self):
		self.assertTrue(periods_overlap("2026-01-01", None, "2026-06-01", None))
