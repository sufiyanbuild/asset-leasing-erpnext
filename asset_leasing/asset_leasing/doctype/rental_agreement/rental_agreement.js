// Rental Agreement - form behaviour.
// UI only. Every rule here is also enforced in rental_agreement.py; nothing on
// this page is authoritative.

frappe.ui.form.on('Rental Agreement', {
	setup(frm) {
		// Only rentable, submitted machines may be hired out.
		frm.set_query('asset', 'items', () => ({
			filters: {
				al_is_rentable: 1,
				docstatus: 1,
				status: ['not in', ['Sold', 'Scrapped', 'Cancelled', 'Capitalized']],
			},
		}));

		// A rental charge item is a service item, never a fixed-asset item.
		frm.set_query('rental_item', 'items', () => ({
			filters: { is_fixed_asset: 0, disabled: 0 },
		}));

		// Equipment goes to a site, not to one of our own yards.
		frm.set_query('site_location', () => ({ filters: { is_group: 0 } }));

		frm.set_query('customer_address', () => ({
			query: 'frappe.contacts.doctype.address.address.address_query',
			filters: { link_doctype: 'Customer', link_name: frm.doc.customer },
		}));
		frm.set_query('contact_person', () => ({
			query: 'frappe.contacts.doctype.contact.contact.contact_query',
			filters: { link_doctype: 'Customer', link_name: frm.doc.customer },
		}));
	},

	refresh(frm) {
		show_pricing_notice(frm);
		show_status_headline(frm);
	},

	customer(frm) {
		if (!frm.doc.customer) return;
		frappe.db
			.get_value('Customer', frm.doc.customer, ['al_hire_blocked', 'al_hire_block_reason'])
			.then((r) => {
				const c = (r && r.message) || {};
				if (!c.al_hire_blocked) return;
				frappe.msgprint({
					title: __('Customer Blocked for Hire'),
					indicator: 'red',
					message: __('{0} is blocked for hire.<br><br>{1}', [
						frm.doc.customer,
						c.al_hire_block_reason || __('No reason recorded.'),
					]),
				});
			});
	},

	is_open_ended(frm) {
		if (frm.doc.is_open_ended) frm.set_value('expected_end_date', null);
	},

	start_date(frm) {
		check_all_assets(frm);
	},

	expected_end_date(frm) {
		check_all_assets(frm);
	},
});

frappe.ui.form.on('Rental Agreement Item', {
	asset(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.asset) return;
		check_availability(frm, row);
	},
});

/** Warn as soon as a machine is picked, rather than at save. */
function check_availability(frm, row) {
	if (!frm.doc.start_date) return;

	frappe.call({
		method: 'asset_leasing.rental.availability.get_asset_availability',
		args: {
			asset: row.asset,
			start_date: frm.doc.start_date,
			end_date: frm.doc.is_open_ended ? null : frm.doc.expected_end_date,
			exclude_agreement: frm.doc.__islocal ? null : frm.doc.name,
		},
		callback(r) {
			const res = r.message;
			if (!res || res.available) return;
			const c = res.conflicts[0];
			frappe.msgprint({
				title: __('Equipment Already Booked'),
				indicator: 'red',
				message: __('{0} is already committed to {1} on agreement {2} ({3} to {4}).', [
					row.asset, c.customer, c.agreement, c.from, c.to || __('open-ended'),
				]),
			});
		},
	});
}

function check_all_assets(frm) {
	(frm.doc.items || []).forEach((row) => {
		if (row.asset) check_availability(frm, row);
	});
}

/** Pricing is deliberately switched off until the client answers Q-14 to Q-18. */
function show_pricing_notice(frm) {
	if (frm.doc.docstatus !== 0) return;

	frappe.db.get_single_value('Asset Leasing Settings', 'pricing_policy_confirmed').then((ok) => {
		if (ok) return;
		frm.dashboard.add_comment(
			__('Monthly rate is recorded, but rental amounts are not calculated yet — the pro-rata policy is still to be confirmed.'),
			'orange',
			true
		);
	});
}

function show_status_headline(frm) {
	if (frm.is_new() || !frm.doc.status) return;
	const colour = {
		Draft: 'grey',
		Approved: 'blue',
		Active: 'orange',
		'Partially Returned': 'yellow',
		Closed: 'green',
		Cancelled: 'red',
	}[frm.doc.status] || 'grey';
	frm.dashboard.set_headline(__('Status: {0}', [frm.doc.status]), colour);
}
