frappe.listview_settings["Rental Agreement"] = {
	add_fields: ["status", "is_overdue", "docstatus"],
	get_indicator(doc) {
		if (doc.is_overdue) return [__("Overdue"), "red", "is_overdue,=,1"];
		const colours = {
			Draft: "gray", Approved: "blue", Active: "orange",
			"Partially Returned": "yellow", Closed: "green", Cancelled: "red",
		};
		return [__(doc.status), colours[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
