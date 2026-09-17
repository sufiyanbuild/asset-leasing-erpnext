// Asset Rental History - filters only; the report is computed on the server.

frappe.query_reports["Asset Rental History"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company")},
		{fieldname: "asset", label: __("Equipment"), fieldtype: "Link", options: "Asset", get_query: () => ({ filters: { al_is_rentable: 1 } })},
		{fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer"},
	],
};
