// Subscription - a long-term hire's billing calendar is owned by its agreement.

frappe.ui.form.on("Subscription", {
	refresh(frm) {
		if (!frm.doc.al_rental_agreement) return;
		frm.dashboard.add_comment(
			__("Billing calendar for Rental Agreement {0}. Change the contract on the agreement, not here.", [
				frappe.utils.get_form_link("Rental Agreement", frm.doc.al_rental_agreement, true),
			]),
			"blue",
			true
		);
	},
});
