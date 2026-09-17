frappe.listview_settings["Rental Return"] = {
	add_fields: ["status", "workflow_state", "inspection_result"],
	get_indicator(doc) {
		if (doc.docstatus === 0 && doc.workflow_state) {
			const colours = { Draft: "gray", "Pending Inspection": "orange", "Damage Assessed": "red" };
			return [__(doc.workflow_state), colours[doc.workflow_state] || "gray", `workflow_state,=,${doc.workflow_state}`];
		}
		const colours = { Inspected: "green", Cancelled: "red", Draft: "gray" };
		return [__(doc.status), colours[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
