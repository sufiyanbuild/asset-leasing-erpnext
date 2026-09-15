app_name = "asset_leasing"
app_title = "Asset Leasing"
app_publisher = "Sufiyan Shaikh"
app_description = "Equipment and plant hire lifecycle for ERPNext (ERT)"
app_email = "sufiyanshaikh1414@gmail.com"
app_license = "mit"

# Fail fast on a bare Frappe site rather than half-installing.
required_apps = ["erpnext"]

after_install = "asset_leasing.setup.install.after_install"

# Re-applies the al_ custom fields idempotently, so a core upgrade that drops a
# column self-heals on the next migrate.
after_migrate = "asset_leasing.setup.install.after_migrate"

# Everything this app configures ships here, so the whole configuration moves
# with the app. Nothing is ever created through the user interface.
#
# Custom DocPerm is deliberately NOT a fixture. Frappe ignores standard DocPerm
# for any DocType that has even one Custom DocPerm row, so importing only the
# Leasing rows would strip Accounts Manager and Accounts User off Sales Invoice.
# setup_permissions() owns those rows instead and runs from both after_install
# and after_migrate; it calls frappe.permissions.add_permission, which copies
# the standard rows in first.
# Custom Field is empty at P0 - the al_ fields arrive in P1.
fixtures = [
	{"dt": "Role", "filters": [["role_name", "like", "Leasing %"]]},
	{"dt": "Custom Field", "filters": [["fieldname", "like", "al_%"]]},
]

# P1 business rules. Every handler on a shared DocType exits immediately when
# its own marker field is absent, so leasing rules never fire on an unrelated
# document - this site may one day host more than one app.
doc_events = {
	"Asset": {"validate": "asset_leasing.events.asset.validate"},
	"Item": {"validate": "asset_leasing.events.item.validate"},
	"Customer": {"validate": "asset_leasing.events.customer.validate"},
	"Sales Invoice": {"validate": "asset_leasing.events.sales_invoice.validate"},
	"Asset Repair": {"validate": "asset_leasing.events.asset_repair.validate"},
}

# Form behaviour only. Loaded per DocType rather than app-wide so these scripts
# are not parsed on every page. No Client Script records are ever created.
doctype_js = {
	"Asset": "public/js/asset.js",
	"Item": "public/js/item.js",
	"Customer": "public/js/customer.js",
	"Sales Invoice": "public/js/sales_invoice.js",
	"Quotation": "public/js/quotation.js",
}

# P1 adds no scheduled jobs and no notifications - those are P8.
