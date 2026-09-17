"""Common set-up for the lifecycle tests (P3 onwards)."""

import frappe
from frappe.tests import IntegrationTestCase

from asset_leasing.tests.fixtures import (
	PREFIX,
	billing_settings,
	ensure_company,
	make_customer,
	make_rentable_asset,
	make_site,
	make_yard,
)


class LeasingTestCase(IntegrationTestCase):
	"""A company, a customer, a yard, a site, and the confirmed pricing and
	billing configuration. Each test gets a machine of its own, because rental
	documents write through db.set_value and comments that outlive a single
	test inside the class transaction."""

	settings_overrides = {}

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = ensure_company()
		cls.customer = make_customer(f"{PREFIX} Hirer")
		cls.other_customer = make_customer(f"{PREFIX} Other Hirer")
		cls.yard = make_yard()
		cls.site = make_site()
		cls.other_site = make_site(f"{PREFIX} Second Site")
		cls.enterClassContext(cls.change_settings(
			"Asset Leasing Settings", {**billing_settings(cls.company), **cls.settings_overrides}
		))

	def setUp(self):
		super().setUp()
		self.asset = self.new_asset()

	def new_asset(self, suffix=""):
		return make_rentable_asset(f"{self.__class__.__name__[:10]}-{self._testMethodName[-22:]}{suffix}")

	def status(self, asset=None):
		return frappe.db.get_value("Asset", asset or self.asset, "al_rental_status")
