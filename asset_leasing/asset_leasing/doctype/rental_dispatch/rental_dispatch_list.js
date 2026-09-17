frappe.listview_settings["Rental Dispatch"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colours = { Draft: "gray", Dispatched: "orange", Cancelled: "red" };
		return [__(doc.status), colours[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
