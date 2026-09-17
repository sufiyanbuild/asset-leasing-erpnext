// Rental Receivables - filters only; the report is computed on the server.

frappe.query_reports["Rental Receivables"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company")},
		{fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer"},
		{fieldname: "as_on", label: __("As On"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today()},
	],
};
