// Asset - rental form behaviour.
// UI only. Every rule here is also enforced server-side in events/asset.py;
// nothing on this page is authoritative.

frappe.ui.form.on('Asset', {
	setup(frm) {
		// Make the fixed-asset trap unreachable from the form in the first place.
		frm.set_query('al_rental_item', () => ({
			filters: { is_fixed_asset: 0, disabled: 0, al_is_rental_item: 1 },
		}));

		// A machine's home is one of our yards, never a customer site.
		frm.set_query('al_base_location', () => ({
			filters: { al_location_type: 'Owned Yard', is_group: 0 },
		}));
	},

	refresh(frm) {
		if (!frm.doc.al_is_rentable || frm.is_new()) return;

		const colour = {
			'Available': 'green',
			'Reserved': 'blue',
			'On Hire': 'orange',
			'In Transit': 'purple',
			'Under Inspection': 'yellow',
			'Under Repair': 'red',
			'Retired': 'grey',
		}[frm.doc.al_rental_status] || 'grey';

		let headline = __('Rental status: {0}', [frm.doc.al_rental_status || __('Available')]);
		if (frm.doc.al_current_customer) {
			headline += ' · ' + __('{0} ({1})', [frm.doc.al_current_customer, frm.doc.al_current_agreement || '']);
		}
		frm.dashboard.set_headline(headline, colour);

		if (['Expired', 'Expiring Soon'].includes(frm.doc.al_compliance_status)) {
			frm.dashboard.add_comment(
				frm.doc.al_compliance_status === 'Expired'
					? __('A compliance document (insurance, fitness or permit) has expired. This machine cannot be dispatched.')
					: __('A compliance document (insurance, fitness or permit) expires within 30 days.'),
				frm.doc.al_compliance_status === 'Expired' ? 'red' : 'orange',
				true
			);
		}

		frm.add_custom_button(__('Hire History'), () => {
			frappe.set_route('query-report', 'Asset Rental History', { company: frm.doc.company, asset: frm.doc.name });
		}, __('View'));
	},

	al_is_rentable(frm) {
		if (frm.doc.al_is_rentable) return;
		frm.set_value('al_rental_item', null);
		frm.set_value('al_base_location', null);
	},

	al_rental_item(frm) {
		if (!frm.doc.al_rental_item) return;

		frappe.db.get_value('Item', frm.doc.al_rental_item, 'is_fixed_asset').then((r) => {
			if (!(r && r.message && r.message.is_fixed_asset)) return;
			frappe.msgprint({
				title: __('Fixed Asset Item Cannot Bill Rent'),
				indicator: 'red',
				message: __(
					'Item {0} is a Fixed Asset item. ERPNext books a fixed-asset item on a Sales Invoice as an asset <b>disposal</b> — this machine would be marked <i>Sold</i> on its first rent invoice.<br><br>Use a non-stock service item instead.',
					[frm.doc.al_rental_item]
				),
			});
			frm.set_value('al_rental_item', null);
		});
	},
});
