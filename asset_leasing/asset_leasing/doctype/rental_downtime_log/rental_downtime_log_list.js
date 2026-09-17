frappe.listview_settings["Rental Downtime Log"] = {
	add_fields: ["workflow_state", "is_creditable"],
	get_indicator(doc) {
		const colours = { Draft: "gray", Pending: "orange", Approved: "green", Rejected: "red" };
		const state = doc.workflow_state || (doc.docstatus === 1 ? "Approved" : "Draft");
		return [__(state), colours[state] || "gray", `workflow_state,=,${state}`];
	},
};
