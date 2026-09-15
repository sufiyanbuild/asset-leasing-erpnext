// Quotation - restrict the hire site to a real location.

frappe.ui.form.on('Quotation', {
	setup(frm) {
		frm.set_query('al_site_location', () => ({ filters: { is_group: 0 } }));
	},
});
