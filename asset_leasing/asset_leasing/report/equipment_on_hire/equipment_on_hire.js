// Equipment On Hire - filters only; the report is computed on the server.

frappe.query_reports["Equipment On Hire"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company")},
		{fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer"},
	],
};
