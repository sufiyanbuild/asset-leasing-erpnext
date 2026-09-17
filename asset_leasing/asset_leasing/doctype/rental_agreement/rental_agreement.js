// Rental Agreement - form behaviour.
// UI only. Every rule here is also enforced in rental_agreement.py; nothing on
// this page is authoritative. The availability labels are hints drawn from the
// same engine that validates the agreement on save.

const AL_LEVELS = {
	available: { colour: "green", marker: "✓" },
	caution: { colour: "orange", marker: "⚠" },
	unavailable: { colour: "red", marker: "✕" },
};

frappe.ui.form.on("Rental Agreement", {
	setup(frm) {
		al_install_picker_decoration();

		// Rentable, submitted machines of this company, labelled with their
		// availability for the agreement dates and listed available-first.
		frm.set_query("asset", "items", () => ({
			query: "asset_leasing.api.rentable_asset_query",
			filters: {
				company: frm.doc.company || "",
				start_date: frm.doc.start_date || "",
				end_date: frm.doc.is_open_ended ? "" : frm.doc.expected_end_date || "",
				is_open_ended: frm.doc.is_open_ended ? 1 : 0,
				agreement: frm.is_new() ? "" : frm.doc.name,
			},
		}));

		// A rental charge item is a service item, never a fixed-asset item.
		frm.set_query("rental_item", "items", () => ({
			filters: { is_fixed_asset: 0, disabled: 0 },
		}));

		// Equipment goes to a site, not to one of our own yards.
		frm.set_query("site_location", () => ({
			filters: { is_group: 0, al_location_type: ["!=", "Owned Yard"] },
		}));

		frm.set_query("customer_address", () => ({
			query: "frappe.contacts.doctype.address.address.address_query",
			filters: { link_doctype: "Customer", link_name: frm.doc.customer },
		}));
		frm.set_query("contact_person", () => ({
			query: "frappe.contacts.doctype.contact.contact.contact_query",
			filters: { link_doctype: "Customer", link_name: frm.doc.customer },
		}));
	},

	refresh(frm) {
		al_prepare_asset_column(frm);
		al_refresh_availability(frm);
		show_pricing_notice(frm);
		show_status_headline(frm);
		add_actions(frm);
	},

	customer(frm) {
		if (!frm.doc.customer) return;
		frappe.call({
			method: "asset_leasing.api.get_customer_hire_status",
			args: { customer: frm.doc.customer, company: frm.doc.company },
			callback(r) {
				const c = r.message || {};
				if (c.blocked) {
					frappe.msgprint({
						title: __("Customer Blocked for Hire"),
						indicator: "red",
						message: __("{0} is blocked for hire.<br><br>{1}", [
							frm.doc.customer,
							c.reason || __("No reason recorded."),
						]),
					});
				} else if (c.exceeded) {
					frappe.msgprint({
						title: __("Credit Limit Exceeded"),
						indicator: "red",
						message: __("{0} has {1} outstanding against a credit limit of {2}.", [
							frm.doc.customer,
							format_currency(c.outstanding),
							format_currency(c.credit_limit),
						]),
					});
				}
			},
		});
	},

	agreement_type(frm) {
		if (frm.doc.agreement_type === "Long Term Contract" && frm.doc.is_open_ended) {
			frm.set_value("is_open_ended", 0);
			frappe.show_alert({
				message: __("A Long Term Contract runs for a fixed term."),
				indicator: "orange",
			});
		}
	},

	is_open_ended(frm) {
		if (frm.doc.is_open_ended) frm.set_value("expected_end_date", null);
		al_refresh_availability(frm);
	},

	start_date(frm) {
		al_refresh_availability(frm, true);
	},

	expected_end_date(frm) {
		al_refresh_availability(frm, true);
	},

	company(frm) {
		al_refresh_availability(frm);
	},
});

frappe.ui.form.on("Rental Agreement Item", {
	asset(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.asset) return;
		al_refresh_availability(frm, true);
	},

	items_remove(frm) {
		al_refresh_availability(frm);
	},
});

// ------------------------------------------------------------ availability
/**
 * Decorate options in the equipment picker.
 *
 * frappe.ui.form.ControlLink calls custom_awesomplete_filter once when it
 * builds its dropdown. The hook is added here for the Rental Agreement Item
 * equipment field only; every other link field is left untouched. Each option
 * keeps its full text description (read by screen readers) and gains a
 * labelled pill, so availability never depends on colour alone.
 */
function al_install_picker_decoration() {
	const proto = frappe.ui.form.ControlLink.prototype;
	if (proto.__al_asset_picker) return;
	const inherited = proto.custom_awesomplete_filter;

	proto.custom_awesomplete_filter = function (awesomplete) {
		if (inherited) inherited.call(this, awesomplete);
		if (!(this.df && this.df.parent === "Rental Agreement Item" && this.df.fieldname === "asset")) {
			return;
		}
		const render = awesomplete.item;
		awesomplete.item = function (item, input, index) {
			const el = render.call(this, item, input, index);
			al_decorate_option(el, this.get_item(item.value));
			return el;
		};
	};
	proto.__al_asset_picker = true;

	if (!document.getElementById("al-asset-picker-style")) {
		const style = document.createElement("style");
		style.id = "al-asset-picker-style";
		style.textContent = `
			.al-asset-option .al-asset-pill { margin-right: 6px; font-weight: 600; }
			.al-asset-option.al-asset-unavailable { background: var(--bg-red); }
			.al-asset-option.al-asset-unavailable strong { text-decoration: line-through; }
			.al-asset-option.al-asset-caution { background: var(--bg-orange); }
			.al-asset-option .al-asset-detail { display: block; }
			.al-asset-option .al-asset-name { display: block; color: var(--text-color); }
			.al-asset-option .al-asset-when { display: block; color: var(--text-muted); }
			.al-asset-cell { margin-left: 6px; }
		`;
		document.head.appendChild(style);
	}
}

function al_level_of(text) {
	text = text || "";
	if (text.startsWith("✕")) return "unavailable";
	if (text.startsWith("⚠")) return "caution";
	if (text.startsWith("✓")) return "available";
	return null;
}

function al_decorate_option(el, data) {
	if (!el || !data) return;
	const description = data.description || "";
	const level = al_level_of(description);
	if (!level) return;

	// "✕ Unavailable — reserved for … ¦ Excavator EX-200 · Excavator"
	const [availability, machine] = description.split(" ¦ ");
	const [status, ...rest] = availability.split(" — ");
	const detail = rest.join(" — ");
	const style = AL_LEVELS[level];

	el.classList.add("al-asset-option", `al-asset-${level}`);
	el.setAttribute("aria-label", `${data.value}: ${description}`);

	const paragraph = el.querySelector("p");
	const small = el.querySelector(".small");
	if (!paragraph) return;

	const pill = document.createElement("span");
	pill.className = `indicator-pill no-indicator-dot ${style.colour} al-asset-pill`;
	pill.textContent = status;
	paragraph.prepend(pill);

	if (small) {
		small.classList.add("al-asset-detail");
		small.textContent = "";
		if (machine) {
			const name = document.createElement("span");
			name.className = "al-asset-name";
			name.textContent = machine;
			small.appendChild(name);
		}
		const when = document.createElement("span");
		when.className = "al-asset-when";
		when.textContent = detail;
		small.appendChild(when);
	}
}

/**
 * Label each machine already on a draft agreement.
 *
 * Grid rows read their field definitions from frappe.meta.docfield_map, so
 * the formatter is attached there once; it looks the label up by the row's
 * parent agreement, so several open agreements never share labels.
 */
const AL_AVAILABILITY = {};
const AL_ANNOUNCED = {};

function al_prepare_asset_column(frm) {
	// the shared definition, the form's copy, and the per-row copies the grid renders from
	frappe.meta.get_docfield("Rental Agreement Item", "asset", frm.doc.name);
	const copies = Object.values(frappe.meta.docfield_copy["Rental Agreement Item"] || {}).map((m) => m.asset);
	const base = (frappe.meta.docfield_map["Rental Agreement Item"] || {}).asset;
	for (const df of [base, ...copies]) {
		if (!df) continue;
		df.filter_description = __("Equipment is labelled with its availability for this agreement's dates.");
		df.formatter = al_asset_formatter;
	}
}

function al_asset_formatter(value, field, options, doc) {
	const plain = frappe.form.formatters.Link(value, field, options, doc);
	const info = value && doc && (AL_AVAILABILITY[doc.parent] || {})[value];
	if (!info || doc.docstatus !== 0) return plain;
	const style = AL_LEVELS[info.level];
	const text = frappe.utils.escape_html(info.text);
	return `${plain}<span class="indicator-pill no-indicator-dot ${style.colour} al-asset-cell"
		title="${text}" aria-label="${text}">${style.marker} ${frappe.utils.escape_html(info.label)}</span>`;
}

function al_refresh_availability(frm, announce) {
	if (frm.doc.docstatus !== 0) return;
	const assets = (frm.doc.items || []).map((d) => d.asset).filter(Boolean);
	if (!assets.length) {
		AL_AVAILABILITY[frm.doc.name] = {};
		return;
	}
	frappe.call({
		method: "asset_leasing.api.get_assets_availability",
		args: {
			assets,
			start_date: frm.doc.start_date,
			end_date: frm.doc.is_open_ended ? null : frm.doc.expected_end_date,
			exclude_agreement: frm.is_new() ? null : frm.doc.name,
		},
		callback(r) {
			AL_AVAILABILITY[frm.doc.name] = r.message || {};
			al_prepare_asset_column(frm);
			frm.fields_dict.items.grid.refresh();
			if (!announce) return;
			// Warn once per machine and period; re-validating the same pick stays quiet.
			const announced = (AL_ANNOUNCED[frm.doc.name] = AL_ANNOUNCED[frm.doc.name] || new Set());
			const period = `${frm.doc.start_date}|${frm.doc.is_open_ended ? "" : frm.doc.expected_end_date}`;
			const blocked = Object.entries(AL_AVAILABILITY[frm.doc.name]).filter(([asset, info]) => {
				const key = `${asset}|${period}`;
				if (info.level !== "unavailable" || announced.has(key)) return false;
				announced.add(key);
				return true;
			});
			if (blocked.length) {
				frappe.msgprint({
					title: __("Equipment Already Booked"),
					indicator: "red",
					message: blocked
						.map(([asset, info]) => `<b>${asset}</b>: ${frappe.utils.escape_html(info.detail)}`)
						.join("<br>"),
				});
			}
		},
	});
}

// ------------------------------------------------------------- headline
function show_pricing_notice(frm) {
	if (frm.doc.docstatus !== 0 || frm.doc.agreement_type === "Long Term Contract") return;
	frappe.db.get_single_value("Asset Leasing Settings", "pricing_policy_confirmed").then((ok) => {
		if (ok) return;
		frm.dashboard.add_comment(
			__("Monthly rate is recorded, but rental amounts are not calculated — the pro-rata policy is not confirmed in Asset Leasing Settings."),
			"orange",
			true
		);
	});
}

function show_status_headline(frm) {
	if (frm.is_new() || !frm.doc.status) return;
	const colour =
		{
			Draft: "gray",
			Approved: "blue",
			Active: "orange",
			"Partially Returned": "yellow",
			Closed: "green",
			Cancelled: "red",
		}[frm.doc.status] || "gray";
	let text = __("Status: {0}", [__(frm.doc.status)]);
	if (frm.doc.is_overdue) {
		text += " · " + __("Overdue since {0}", [frappe.datetime.str_to_user(frm.doc.overdue_since)]);
	}
	frm.dashboard.set_headline(text, frm.doc.is_overdue ? "red" : colour);
}

// --------------------------------------------------------------- actions
function add_actions(frm) {
	if (frm.doc.docstatus !== 1) return;
	const lines = frm.doc.items || [];
	const pending = lines.some((d) => d.line_status === "Pending Dispatch");
	const on_hire = lines.filter((d) => d.line_status === "On Hire");
	const live = ["Approved", "Active", "Partially Returned"].includes(frm.doc.status);
	const create = __("Create");

	if (live && pending && frappe.model.can_create("Rental Dispatch")) {
		frm.add_custom_button(__("Dispatch"), () => {
			frappe.model.with_doctype("Rental Dispatch", () => {
				const doc = frappe.model.get_new_doc("Rental Dispatch");
				doc.rental_agreement = frm.doc.name;
				frappe.set_route("Form", "Rental Dispatch", doc.name);
			});
		}, create);
	}

	if (on_hire.length && frappe.model.can_create("Rental Return")) {
		frm.add_custom_button(__("Return"), () => {
			frappe.model.with_doctype("Rental Return", () => {
				const doc = frappe.model.get_new_doc("Rental Return");
				doc.rental_agreement = frm.doc.name;
				frappe.set_route("Form", "Rental Return", doc.name);
			});
		}, create);
	}

	if (on_hire.length && frappe.model.can_create("Rental Downtime Log")) {
		frm.add_custom_button(__("Downtime Log"), () => {
			frappe.new_doc("Rental Downtime Log", {
				rental_agreement: frm.doc.name,
				asset: on_hire.length === 1 ? on_hire[0].asset : undefined,
			});
		}, create);
	}

	if (on_hire.length && frappe.model.can_create("Rental Dispatch")) {
		frm.add_custom_button(__("Transfer to Another Site"), () => transfer_dialog(frm, on_hire), __("Actions"));
	}

	if (frappe.model.can_create("Payment Entry") || frappe.model.can_create("Sales Invoice")) {
		frappe.call({
			method: "asset_leasing.asset_leasing.doctype.rental_agreement.rental_agreement.get_billing_summary",
			args: { agreement: frm.doc.name },
			callback(r) {
				const s = r.message || {};
				if (frappe.model.can_create("Payment Entry")) {
					if (flt(frm.doc.security_deposit_amount) > flt(s.deposit_received)) {
						frm.add_custom_button(__("Deposit Receipt"), () => make_deposit(frm, "Deposit Received"), create);
					}
					if (flt(s.deposit_refundable) > 0) {
						frm.add_custom_button(__("Deposit Refund"), () => make_deposit(frm, "Deposit Refund"), create);
					}
				}
				if (frappe.model.can_create("Sales Invoice")) {
					const dispatched = lines.some((d) => d.line_status !== "Pending Dispatch");
					if (flt(frm.doc.mobilisation_charge) > 0 && dispatched && !s.transport.mobilisation) {
						frm.add_custom_button(__("Mobilisation Invoice"), () => make_transport(frm, "mobilisation"), create);
					}
					if (flt(frm.doc.demobilisation_charge) > 0 && frm.doc.status === "Closed" && !s.transport.demobilisation) {
						frm.add_custom_button(__("Demobilisation Invoice"), () => make_transport(frm, "demobilisation"), create);
					}
				}
				if (s.draft_invoices && s.draft_invoices.length) {
					frm.dashboard.add_comment(
						__("{0} draft invoice(s) waiting for Finance: {1}", [
							s.draft_invoices.length,
							s.draft_invoices.map((n) => frappe.utils.get_form_link("Sales Invoice", n, true)).join(", "),
						]),
						"blue",
						true
					);
				}
			},
		});
	}

	if (frm.doc.subscription) {
		frm.add_custom_button(__("Subscription"), () =>
			frappe.set_route("Form", "Subscription", frm.doc.subscription), __("View"));
	}
	frm.add_custom_button(__("Invoices"), () =>
		frappe.set_route("List", "Sales Invoice", { al_rental_agreement: frm.doc.name }), __("View"));
}

function transfer_dialog(frm, on_hire) {
	const dialog = new frappe.ui.Dialog({
		title: __("Transfer to Another Site"),
		fields: [
			{
				fieldname: "asset", fieldtype: "Select", label: __("Equipment"), reqd: 1,
				options: on_hire.map((d) => ({ value: d.asset, label: `${d.asset}: ${d.asset_name || ""}` })),
				default: on_hire.length === 1 ? on_hire[0].asset : undefined,
			},
			{
				fieldname: "target_location", fieldtype: "Link", options: "Location", label: __("New Site"), reqd: 1,
				get_query: () => ({ filters: { is_group: 0, al_location_type: ["!=", "Owned Yard"] } }),
			},
			{ fieldname: "transfer_datetime", fieldtype: "Datetime", label: __("Moved On"), default: frappe.datetime.now_datetime() },
			{ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
		],
		primary_action_label: __("Transfer"),
		primary_action(values) {
			frappe.call({
				method: "asset_leasing.asset_leasing.doctype.rental_agreement.rental_agreement.transfer_equipment",
				args: { agreement: frm.doc.name, ...values },
				freeze: true,
				callback(r) {
					dialog.hide();
					frappe.show_alert({ message: __("Moved - {0}", [r.message]), indicator: "green" });
					frm.reload_doc();
				},
			});
		},
	});
	dialog.show();
}

function make_deposit(frm, kind) {
	frappe.call({
		method: "asset_leasing.rental.deposits.make_deposit_entry",
		args: { agreement: frm.doc.name, kind },
		callback(r) {
			const doc = frappe.model.sync(r.message)[0];
			frappe.set_route("Form", doc.doctype, doc.name);
		},
	});
}

function make_transport(frm, kind) {
	frappe.call({
		method: "asset_leasing.rental.billing.make_transport_invoice",
		args: { agreement: frm.doc.name, kind },
		freeze: true,
		callback(r) {
			if (r.message) frappe.set_route("Form", "Sales Invoice", r.message);
		},
	});
}
