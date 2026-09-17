// Payment Entry - security deposit tagging. deposits.py is authoritative.

frappe.ui.form.on("Payment Entry", {
	setup(frm) {
		frm.set_query("al_rental_agreement", () => ({
			filters: { docstatus: 1, customer: frm.doc.party || "" },
		}));
	},

	al_deposit_type(frm) {
		if (!frm.doc.al_deposit_type) return;
		frappe.db.get_single_value("Asset Leasing Settings", "deposit_liability_account").then((account) => {
			if (!account) {
				frappe.msgprint(__("Set the Security Deposit Liability Account in Asset Leasing Settings first."));
				return;
			}
			const field = frm.doc.al_deposit_type === "Deposit Received" ? "paid_from" : "paid_to";
			frm.set_value("payment_type", frm.doc.al_deposit_type === "Deposit Received" ? "Receive" : "Pay");
			frm.set_value(field, account);
		});
	},
});
