// Sales Invoice - equipment selection and a nudge when a rental invoice
// identifies no equipment. Authoritative checks are events/sales_invoice.py.

frappe.ui.form.on('Sales Invoice', {
	setup(frm) {
		frm.set_query('al_asset', 'items', () => ({
			filters: { al_is_rentable: 1, docstatus: 1 },
		}));
	},

	al_invoice_purpose(frm) {
		if (frm.doc.al_invoice_purpose !== 'Rental') return;
		const tagged = (frm.doc.items || []).some((d) => d.al_asset);
		if (!tagged) {
			frappe.show_alert({
				message: __('Set Equipment on at least one line for a rental invoice.'),
				indicator: 'orange',
			});
		}
	},
});
