// Rental Dispatch - form behaviour. UI only; rental_dispatch.py is authoritative.

frappe.ui.form.on("Rental Dispatch", {
	setup(frm) {
		frm.set_query("rental_agreement", () => ({
			filters: { docstatus: 1, status: ["in", ["Approved", "Active", "Partially Returned"]] },
		}));
		frm.set_query("from_location", () => ({
			filters: { is_group: 0, al_location_type: "Owned Yard" },
		}));
		// Machines held for this agreement. The server matches each to its agreement line.
		frm.set_query("asset", "items", () => ({
			filters: { al_is_rentable: 1, al_current_agreement: frm.doc.rental_agreement || "" },
		}));
	},

	onload(frm) {
		if (frm.is_new() && frm.doc.rental_agreement && !(frm.doc.items || []).some((d) => d.asset)) {
			pull_pending(frm);
		}
	},

	refresh(frm) {
		toggle_transport(frm);
		if (frm.doc.docstatus === 0 && frm.doc.rental_agreement) {
			frm.add_custom_button(__("Get Equipment From Agreement"), () => pull_pending(frm));
		}
		if (frm.doc.docstatus === 1) {
			const done = (frm.doc.items || []).length;
			frm.dashboard.set_headline(
				__("{0} machine(s) released to {1}.", [done, frm.doc.to_location]), "orange"
			);
			if (frappe.model.can_create("Rental Return")) {
				frm.add_custom_button(__("Return"), () => {
					frappe.model.with_doctype("Rental Return", () => {
						const doc = frappe.model.get_new_doc("Rental Return");
						doc.rental_agreement = frm.doc.rental_agreement;
						doc.rental_dispatch = frm.doc.name;
						frappe.set_route("Form", "Rental Return", doc.name);
					});
				}, __("Create"));
			}
		}
	},

	rental_agreement(frm) {
		frm.clear_table("items");
		frm.refresh_field("items");
		if (frm.doc.rental_agreement) pull_pending(frm);
	},

	transport_mode(frm) {
		toggle_transport(frm);
	},
});

function pull_pending(frm) {
	frappe.call({
		method: "asset_leasing.asset_leasing.doctype.rental_dispatch.rental_dispatch.get_pending_items",
		args: { rental_agreement: frm.doc.rental_agreement },
		callback(r) {
			const data = r.message || {};
			frm.clear_table("items");
			(data.items || []).forEach((d) => {
				const row = frm.add_child("items");
				row.asset = d.asset;
				row.asset_name = d.asset_name;
				row.agreement_item = d.agreement_item;
				row.meter_reading_out = d.meter_reading_out;
			});
			if (data.from_location && !frm.doc.from_location) frm.set_value("from_location", data.from_location);
			if (data.to_location) frm.set_value("to_location", data.to_location);
			frm.refresh_field("items");
			if (!(data.items || []).length) {
				frappe.show_alert({ message: __("Nothing is waiting to be dispatched on this agreement."), indicator: "orange" });
			}
		},
	});
}

function toggle_transport(frm) {
	const needs_vehicle = ["Own Vehicle", "Hired Transport"].includes(frm.doc.transport_mode);
	frm.toggle_reqd(["vehicle_no", "driver_name"], needs_vehicle);
}
