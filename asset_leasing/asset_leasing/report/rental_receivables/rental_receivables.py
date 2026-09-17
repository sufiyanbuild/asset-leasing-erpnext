"""AL-30 - outstanding rental invoices by customer and agreement, aged.

Complements, not replaces, the standard Accounts Receivable report.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate

from asset_leasing.reports_common import require

BUCKETS = [(30, "range_0_30"), (60, "range_31_60"), (90, "range_61_90")]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	require(filters, "company", "as_on")
	conditions = {"company": filters.company, "docstatus": 1, "al_rental_agreement": ["is", "set"],
				  "outstanding_amount": ["!=", 0], "posting_date": ["<=", filters.as_on]}
	if filters.customer:
		conditions["customer"] = filters.customer
	invoices = frappe.get_all(
		"Sales Invoice", filters=conditions,
		fields=["name", "customer", "al_rental_agreement", "al_invoice_purpose", "posting_date", "due_date",
				"grand_total", "outstanding_amount"],
		order_by="customer asc, due_date asc",
	)
	rows = []
	for inv in invoices:
		age = max(0, date_diff(getdate(filters.as_on), inv.due_date or inv.posting_date))
		row = {**inv, "age": age, "range_0_30": 0.0, "range_31_60": 0.0, "range_61_90": 0.0, "range_90_above": 0.0}
		for limit, field in BUCKETS:
			if age <= limit:
				row[field] = flt(inv.outstanding_amount)
				break
		else:
			row["range_90_above"] = flt(inv.outstanding_amount)
		rows.append(row)
	columns = [
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 180},
		{"label": _("Agreement"), "fieldname": "al_rental_agreement", "fieldtype": "Link", "options": "Rental Agreement", "width": 130},
		{"label": _("Invoice"), "fieldname": "name", "fieldtype": "Link", "options": "Sales Invoice", "width": 150},
		{"label": _("Purpose"), "fieldname": "al_invoice_purpose", "fieldtype": "Data", "width": 120},
		{"label": _("Posted"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Due"), "fieldname": "due_date", "fieldtype": "Date", "width": 100},
		{"label": _("Invoice Total"), "fieldname": "grand_total", "fieldtype": "Currency", "width": 120},
		{"label": _("Outstanding"), "fieldname": "outstanding_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Days Past Due"), "fieldname": "age", "fieldtype": "Int", "width": 100},
		{"label": _("0-30"), "fieldname": "range_0_30", "fieldtype": "Currency", "width": 110},
		{"label": _("31-60"), "fieldname": "range_31_60", "fieldtype": "Currency", "width": 110},
		{"label": _("61-90"), "fieldname": "range_61_90", "fieldtype": "Currency", "width": 110},
		{"label": _("90+"), "fieldname": "range_90_above", "fieldtype": "Currency", "width": 110},
	]
	return columns, rows, None, None, None, True
