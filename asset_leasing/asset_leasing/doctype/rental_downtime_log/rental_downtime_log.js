// Rental Downtime Log - form behaviour. UI only.

frappe.ui.form.on("Rental Downtime Log", {
	setup(frm) {
		frm.set_query("rental_agreement", () => ({
			filters: { docstatus: 1, status: ["in", ["Active", "Partially Returned"]] },
		}));
		frm.set_query("asset", () => ({
			query: "asset_leasing.asset_leasing.doctype.rental_downtime_log.rental_downtime_log.hired_asset_query",
			filters: { rental_agreement: frm.doc.rental_agreement || "" },
		}));
	},

	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.dashboard.set_headline(
				frm.doc.is_creditable
					? __("Approved - {0} hours credited against the hire.", [frm.doc.downtime_hours])
					: __("Approved - recorded for analysis; not credited."),
				frm.doc.is_creditable ? "green" : "blue"
			);
		}
	},

	from_datetime: set_hours,
	to_datetime: set_hours,
});

function set_hours(frm) {
	if (!(frm.doc.from_datetime && frm.doc.to_datetime)) return;
	const hours = moment(frm.doc.to_datetime).diff(moment(frm.doc.from_datetime), "minutes") / 60;
	frm.set_value("downtime_hours", hours > 0 ? hours : 0);
}
