// Item - warn early when a rental charge item is configured as a fixed asset.
// Authoritative check is events/item.py.

frappe.ui.form.on('Item', {
	al_is_rental_item(frm) {
		if (frm.doc.al_is_rental_item && frm.doc.is_fixed_asset) {
			frappe.msgprint({
				title: __('Conflicting Item Configuration'),
				indicator: 'red',
				message: __(
					'An item cannot be both a Fixed Asset item and a Rental Charge Item. A rental charge item must be a non-stock service item.'
				),
			});
		}
	},

	is_fixed_asset(frm) {
		if (frm.doc.is_fixed_asset && frm.doc.al_is_rental_item) {
			frm.set_value('al_is_rental_item', 0);
			frappe.show_alert({
				message: __('Is Rental Charge Item cleared — a fixed-asset item cannot bill rent.'),
				indicator: 'orange',
			});
		}
	},
});
