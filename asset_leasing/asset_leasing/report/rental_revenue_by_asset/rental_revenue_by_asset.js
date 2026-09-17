// Rental Revenue by Asset - filters only; the report is computed on the server.

frappe.query_reports["Rental Revenue by Asset"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company")},
		{fieldname: "from_date", label: __("From Date"), fieldtype: "Date"},
		{fieldname: "to_date", label: __("To Date"), fieldtype: "Date"},
		{fieldname: "asset_category", label: __("Asset Category"), fieldtype: "Link", options: "Asset Category"},
	],
};
