frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Rental Revenue by Category"] = {
	method: "asset_leasing.asset_leasing.dashboard_chart_source.rental_revenue_by_category.rental_revenue_by_category.get",
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company"), reqd: 1 },
	],
};
