// Asset Availability - filters only; the report is computed on the server.

frappe.query_reports["Asset Availability"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company")},
		{fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today()},
		{fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.add_days(frappe.datetime.get_today(), 30)},
		{fieldname: "asset_category", label: __("Asset Category"), fieldtype: "Link", options: "Asset Category"},
	],
};
