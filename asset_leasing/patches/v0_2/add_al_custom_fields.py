"""P1: install the al_ custom field layer.

Idempotent by construction - create_custom_fields(update=True) inserts what is
missing and updates what has drifted, so running it repeatedly is a no-op.
"""

from asset_leasing.setup.custom_fields import create_al_custom_fields


def execute():
	count = create_al_custom_fields()
	print(f"asset_leasing: {count} al_ custom fields applied.")
