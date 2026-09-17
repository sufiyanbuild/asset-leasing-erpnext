// Rental Return - form behaviour. UI only; rental_return.py recomputes every figure.

frappe.ui.form.on("Rental Return", {
	setup(frm) {
		frm.set_query("rental_agreement", () => ({
			filters: { docstatus: 1, status: ["in", ["Active", "Partially Returned"]] },
		}));
		frm.set_query("rental_dispatch", () => ({
			filters: { docstatus: 1, rental_agreement: frm.doc.rental_agreement },
		}));
		frm.set_query("to_location", () => ({
			filters: { is_group: 0, al_location_type: "Owned Yard" },
		}));
		frm.set_query("asset", "damages", () => ({
			filters: { name: ["in", (frm.doc.items || []).map((d) => d.asset).filter(Boolean)] },
		}));
	},

	onload(frm) {
		if (frm.is_new() && frm.doc.rental_agreement && !(frm.doc.items || []).some((d) => d.asset)) {
			pull_on_hire(frm);
		}
	},

	refresh(frm) {
		toggle_damage(frm);
		if (frm.doc.docstatus === 0 && frm.doc.rental_agreement) {
			frm.add_custom_button(__("Get Equipment On Hire"), () => pull_on_hire(frm));
			preview(frm);
		}
		if (frm.doc.docstatus === 1) {
			show_billing(frm);
		}
	},

	rental_agreement(frm) {
		frm.clear_table("items");
		frm.refresh_field("items");
		if (frm.doc.rental_agreement) pull_on_hire(frm);
	},

	rental_dispatch(frm) {
		if (frm.doc.rental_agreement) pull_on_hire(frm);
	},

	return_datetime(frm) {
		preview(frm);
	},

	adjustment_days(frm) {
		preview(frm);
	},

	inspection_result(frm) {
		toggle_damage(frm);
		const next = frm.doc.inspection_result === "Damage Found" ? null : "Available";
		if (next) {
			(frm.doc.items || []).forEach((d) => {
				if (!d.post_return_status) frappe.model.set_value(d.doctype, d.name, "post_return_status", next);
			});
		}
	},
});

frappe.ui.form.on("Rental Return Item", {
	meter_reading_in(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.meter_reading_in || row.meter_reading_out == null) return;
		const used = flt(row.meter_reading_in) - flt(row.meter_reading_out);
		frappe.model.set_value(cdt, cdn, "meter_hours_used", used);
		if (used < 0) {
			frappe.show_alert({
				message: __("{0}: meter reading in is below the reading at dispatch ({1}).", [row.asset, row.meter_reading_out]),
				indicator: "red",
			});
		}
	},
});

frappe.ui.form.on("Rental Damage Item", {
	chargeable_to_customer(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const item = (frm.doc.items || []).find((d) => d.asset === row.asset);
		if (row.chargeable_to_customer && item && row.severity !== "Total Loss") {
			frappe.model.set_value(item.doctype, item.name, "post_return_status", "Under Repair");
		}
	},
	asset(frm, cdt, cdn) {
		frm.script_manager.trigger("chargeable_to_customer", cdt, cdn);
	},
});

function pull_on_hire(frm) {
	frappe.call({
		method: "asset_leasing.asset_leasing.doctype.rental_return.rental_return.get_on_hire_items",
		args: { rental_agreement: frm.doc.rental_agreement, rental_dispatch: frm.doc.rental_dispatch || null },
		callback(r) {
			const data = r.message || {};
			frm.clear_table("items");
			(data.items || []).forEach((d) => {
				const row = frm.add_child("items");
				Object.assign(row, {
					asset: d.asset,
					asset_name: d.asset_name,
					agreement_item: d.agreement_item,
					dispatch_datetime: d.dispatch_datetime,
					source_location: d.source_location,
				});
			});
			if (data.to_location && !frm.doc.to_location) frm.set_value("to_location", data.to_location);
			frm.refresh_field("items");
			preview(frm);
		},
	});
}

function preview(frm) {
	const items = (frm.doc.items || []).filter((d) => d.asset).map((d) => ({ asset: d.asset }));
	if (!items.length || !frm.doc.return_datetime) return;
	frappe.call({
		method: "asset_leasing.asset_leasing.doctype.rental_return.rental_return.preview_return",
		args: {
			rental_agreement: frm.doc.rental_agreement,
			return_datetime: frm.doc.return_datetime,
			items,
			adjustment_days: frm.doc.adjustment_days || 0,
		},
		callback(r) {
			const data = r.message || {};
			const rows = (data.items || []).map((d) => {
				if (d.elapsed_days == null) {
					return `<li><b>${d.asset}</b>: ${__("return must be after dispatch")}</li>`;
				}
				let text = __("{0} days elapsed, {1} days approved downtime", [
					format_number(d.elapsed_days, null, 2), format_number(d.downtime_days, null, 2),
				]);
				if (d.billable_days != null) {
					text += " → " + __("{0} billable days = {1}", [d.billable_days, format_currency(d.rental_amount)]);
				}
				return `<li><b>${d.asset}</b>: ${text}</li>`;
			});
			let note = "";
			if (data.agreement_type === "Long Term Contract") {
				note = __("Rent for this contract is billed monthly by its Subscription.");
			} else if ((data.pricing_pending || []).length) {
				note = __("Rent is not calculated: the pro-rata policy is not confirmed.");
			}
			frm.dashboard.clear_comment();
			frm.dashboard.add_comment(
				`${__("Preview - recalculated on save")}:<ul style="margin:4px 0 0">${rows.join("")}</ul>${note}`,
				"blue",
				true
			);
		},
	});
}

function show_billing(frm) {
	frappe.db.get_list("Sales Invoice", {
		filters: { al_rental_return: frm.doc.name, docstatus: ["<", 2] },
		fields: ["name", "al_invoice_purpose", "docstatus", "grand_total"],
	}).then((invoices) => {
		const has = (purpose) => invoices.some((i) => i.al_invoice_purpose === purpose);
		if (frappe.model.can_create("Sales Invoice")) {
			if (flt(frm.doc.total_chargeable_damage) > 0 && !has("Damage Recovery")) {
				frm.add_custom_button(__("Damage Invoice"), () => call_and_open(frm,
					"asset_leasing.rental.billing.make_damage_invoice"), __("Create"));
			}
			if (frm.doc.rental_billing_status === "Awaiting Pricing Policy" && !has("Rental")) {
				frm.add_custom_button(__("Rental Invoice"), () => call_and_open(frm,
					"asset_leasing.rental.billing.make_rental_invoice"), __("Create"));
			}
		}
		if (invoices.length) {
			const list = invoices.map((i) =>
				`${frappe.utils.get_form_link("Sales Invoice", i.name, true)} (${__(i.al_invoice_purpose)}, ${i.docstatus ? __("submitted") : __("draft")})`
			).join(", ");
			frm.dashboard.add_comment(__("Invoices: {0}", [list]), "green", true);
		}
	});
}

function call_and_open(frm, method) {
	frappe.call({
		method,
		args: { rental_return: frm.doc.name },
		freeze: true,
		callback(r) {
			if (r.message) frappe.set_route("Form", "Sales Invoice", r.message);
		},
	});
}

function toggle_damage(frm) {
	const damaged = frm.doc.inspection_result === "Damage Found";
	frm.toggle_display("sb_damage", damaged);
	frm.toggle_reqd("damages", damaged);
}
