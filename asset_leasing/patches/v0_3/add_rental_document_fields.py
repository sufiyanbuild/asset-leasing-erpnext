"""P3-P8: custom fields that link to Rental Dispatch and Rental Return, plus the
deposit, subscription and compliance fields. Idempotent."""

from asset_leasing.setup.custom_fields import create_al_custom_fields


def execute():
	count = create_al_custom_fields()
	print(f"asset_leasing: {count} al_ custom fields applied.")
