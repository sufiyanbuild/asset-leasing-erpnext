// Agreement Expiry and Renewal - filters only; the report is computed on the server.

frappe.query_reports["Agreement Expiry and Renewal"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company")},
		{fieldname: "days", label: __("Ending Within (Days)"), fieldtype: "Int", default: 30},
		{fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer"},
	],
};
