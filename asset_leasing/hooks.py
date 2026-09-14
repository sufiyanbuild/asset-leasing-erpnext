app_name = "asset_leasing"
app_title = "Asset Leasing"
app_publisher = "Sufiyan Shaikh"
app_description = "Equipment and plant hire lifecycle for ERPNext (ERT)"
app_email = "sufiyanshaikh1414@gmail.com"
app_license = "mit"

# Fail fast on a bare Frappe site rather than half-installing.
required_apps = ["erpnext"]

after_install = "asset_leasing.setup.install.after_install"

# Everything this app configures ships here, so the whole configuration moves
# with the app. Nothing is ever created through the user interface.
# Custom Field is empty at P0 - the al_ fields arrive in P1.
fixtures = [
	{"dt": "Role", "filters": [["role_name", "like", "Leasing %"]]},
	{"dt": "Custom Field", "filters": [["fieldname", "like", "al_%"]]},
]

# P0 registers no document events and no scheduled jobs. Handlers arrive with
# the DocTypes they belong to, in P2 onward.
