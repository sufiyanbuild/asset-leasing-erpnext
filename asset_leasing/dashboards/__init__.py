"""Connections added to standard DocType dashboards."""

from frappe import _


def asset(data):
	"""Hire history on the Asset form (Section 11, override_doctype_dashboard)."""
	data = data or {}
	fieldnames = data.setdefault("non_standard_fieldnames", {})
	fieldnames.update({
		"Rental Agreement": "asset",
		"Rental Dispatch": "asset",
		"Rental Return": "asset",
		"Rental Downtime Log": "asset",
		"Sales Invoice": "al_asset",
		"Asset Repair": "asset",
	})
	transactions = data.setdefault("transactions", [])
	transactions.append({
		"label": _("Equipment Hire"),
		"items": ["Rental Agreement", "Rental Dispatch", "Rental Return", "Rental Downtime Log"],
	})
	listed = {item for t in transactions for item in t.get("items", [])}
	billing = [d for d in ("Sales Invoice", "Asset Repair") if d not in listed]
	if billing:
		transactions.append({"label": _("Billing"), "items": billing})
	return data
