"""AL-15 - damage found, approved, invoiced and recovered."""

import frappe
from frappe import _
from frappe.utils import flt

from asset_leasing.reports_common import require


def execute(filters=None):
	filters = frappe._dict(filters or {})
	require(filters, "company")
	conditions, values = ["rr.docstatus < 2", "rr.company = %(company)s"], {"company": filters.company}
	if filters.customer:
		conditions.append("rr.customer = %(customer)s")
		values["customer"] = filters.customer
	if filters.from_date:
		conditions.append("date(rr.return_datetime) >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.to_date:
		conditions.append("date(rr.return_datetime) <= %(to_date)s")
		values["to_date"] = filters.to_date
	damages = frappe.db.sql(
		f"""
		select rr.name as rental_return, rr.return_datetime, rr.rental_agreement, rr.customer,
			rr.docstatus, rr.workflow_state, rdi.asset, rdi.severity, rdi.damage_description,
			rdi.estimated_cost, rdi.chargeable_to_customer
		from `tabRental Damage Item` rdi join `tabRental Return` rr on rr.name = rdi.parent
		where {" and ".join(conditions)}
		order by rr.return_datetime desc
		""",
		values,
		as_dict=True,
	)
	invoices = {}
	for inv in frappe.db.sql(
		"""select si.al_rental_return, si.name, si.docstatus, si.grand_total, si.outstanding_amount,
			sii.al_asset, sum(sii.base_net_amount) as amount
		from `tabSales Invoice` si join `tabSales Invoice Item` sii on sii.parent = si.name
		where si.al_invoice_purpose = 'Damage Recovery' and si.docstatus < 2 and si.company = %s
		group by si.name, sii.al_asset""",
		filters.company, as_dict=True,
	):
		invoices[(inv.al_rental_return, inv.al_asset)] = inv
	rows = []
	for d in damages:
		inv = invoices.get((d.rental_return, d.asset))
		invoiced = flt(inv.amount) if inv and inv.docstatus == 1 else 0.0
		share = invoiced / flt(inv.grand_total) if inv and flt(inv.grand_total) else 0
		recovered = (flt(inv.grand_total) - flt(inv.outstanding_amount)) * share if invoiced else 0.0
		rows.append({
			**d,
			"stage": _("Approved") if d.docstatus == 1 else _(d.workflow_state or "Draft"),
			"invoice": inv.name if inv else None,
			"invoice_status": (_("Submitted") if inv.docstatus else _("Draft")) if inv else None,
			"invoiced": invoiced,
			"recovered": flt(recovered, 2),
		})
	columns = [
		{"label": _("Return"), "fieldname": "rental_return", "fieldtype": "Link", "options": "Rental Return", "width": 130},
		{"label": _("Returned"), "fieldname": "return_datetime", "fieldtype": "Datetime", "width": 150},
		{"label": _("Agreement"), "fieldname": "rental_agreement", "fieldtype": "Link", "options": "Rental Agreement", "width": 130},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 170},
		{"label": _("Equipment"), "fieldname": "asset", "fieldtype": "Link", "options": "Asset", "width": 160},
		{"label": _("Severity"), "fieldname": "severity", "fieldtype": "Data", "width": 90},
		{"label": _("Damage"), "fieldname": "damage_description", "fieldtype": "Data", "width": 220},
		{"label": _("Estimated Cost"), "fieldname": "estimated_cost", "fieldtype": "Currency", "width": 120},
		{"label": _("Chargeable"), "fieldname": "chargeable_to_customer", "fieldtype": "Check", "width": 90},
		{"label": _("Stage"), "fieldname": "stage", "fieldtype": "Data", "width": 120},
		{"label": _("Invoice"), "fieldname": "invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 150},
		{"label": _("Invoice Status"), "fieldname": "invoice_status", "fieldtype": "Data", "width": 100},
		{"label": _("Invoiced"), "fieldname": "invoiced", "fieldtype": "Currency", "width": 110},
		{"label": _("Recovered"), "fieldname": "recovered", "fieldtype": "Currency", "width": 110},
	]
	return columns, rows
