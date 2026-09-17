// Quotation - restrict the hire site to a real location, and turn an accepted
// rental quotation into a Rental Agreement.

frappe.ui.form.on("Quotation", {
	setup(frm) {
		frm.set_query("al_site_location", () => ({ filters: { is_group: 0 } }));
	},

	refresh(frm) {
		if (frm.doc.docstatus !== 1 || !frm.doc.al_is_rental || frm.doc.quotation_to !== "Customer") return;
		if (!frappe.model.can_create("Rental Agreement")) return;
		frm.add_custom_button(__("Rental Agreement"), () => {
			frappe.model.open_mapped_doc({
				method: "asset_leasing.asset_leasing.doctype.rental_agreement.rental_agreement.make_rental_agreement",
				frm,
			});
		}, __("Create"));
	},
});
