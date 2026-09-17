frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Utilisation by Category"] = {
	method: "asset_leasing.asset_leasing.dashboard_chart_source.utilisation_by_category.utilisation_by_category.get",
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company"), reqd: 1 },
	],
};
