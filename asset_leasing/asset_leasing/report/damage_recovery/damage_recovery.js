// Damage Recovery - filters only; the report is computed on the server.

frappe.query_reports["Damage Recovery"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company")},
		{fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer"},
		{fieldname: "from_date", label: __("Returned From"), fieldtype: "Date"},
		{fieldname: "to_date", label: __("Returned To"), fieldtype: "Date"},
	],
};
