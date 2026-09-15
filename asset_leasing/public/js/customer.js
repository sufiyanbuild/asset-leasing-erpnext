// Customer - surface a hire block prominently.

frappe.ui.form.on('Customer', {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.al_hire_blocked) return;
		frm.dashboard.set_headline(
			__('Blocked for hire — {0}', [frm.doc.al_hire_block_reason || __('no reason recorded')]),
			'red'
		);
	},
});
