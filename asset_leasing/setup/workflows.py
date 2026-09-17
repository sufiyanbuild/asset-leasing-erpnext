"""The three approval workflows (Section 07).

Only human decisions live in workflows. Operational consequences - Active,
Partially Returned, Closed, On Hire, Returned - are read-only status fields
driven by the documents themselves.

    Rental Agreement Approval  - Approve is the submit.
    Rental Return Inspection   - damage cannot reach an invoice without a
                                 Leasing Manager approving it; the role that
                                 records damage cannot approve its own charge.
    Rental Downtime Approval   - only approved, creditable downtime reduces a bill.

Workflow State and Action names are generic, site-wide records; they are
created if missing and never modified.
"""

import frappe

HIRE_DESK = "Leasing Hire Desk"
YARD = "Leasing Yard Supervisor"
TECH = "Leasing Maintenance Technician"
FINANCE = "Leasing Finance"
MANAGER = "Leasing Manager"

WORKFLOW_NAME = "Rental Agreement Approval"
RETURN_WORKFLOW = "Rental Return Inspection"
DOWNTIME_WORKFLOW = "Rental Downtime Approval"

STATES = [
	("Draft", "Danger"),
	("Pending", "Warning"),
	("Approved", "Success"),
	("Rejected", "Danger"),
	("Pending Inspection", "Warning"),
	("Damage Assessed", "Danger"),
	("Inspected", "Success"),
]

ACTIONS = [
	"Submit for Approval", "Approve", "Reject", "Revise",
	"Send for Inspection", "Pass Inspection", "Record Damage", "Approve Charges",
]

PASSED = 'doc.inspection_result == "Passed"'
DAMAGED = 'doc.inspection_result == "Damage Found"'

WORKFLOWS = {
	WORKFLOW_NAME: {
		"document_type": "Rental Agreement",
		# state, docstatus, who may edit it
		"states": [
			("Draft", "0", HIRE_DESK),
			("Pending", "0", MANAGER),
			("Approved", "1", MANAGER),
			("Rejected", "0", HIRE_DESK),
		],
		# from, action, to, allowed role, condition
		"transitions": [
			("Draft", "Submit for Approval", "Pending", HIRE_DESK, None),
			("Pending", "Approve", "Approved", MANAGER, None),
			("Pending", "Reject", "Rejected", MANAGER, None),
			("Rejected", "Revise", "Draft", HIRE_DESK, None),
		],
	},
	RETURN_WORKFLOW: {
		"document_type": "Rental Return",
		"states": [
			("Draft", "0", YARD),
			("Pending Inspection", "0", TECH),
			("Damage Assessed", "0", MANAGER),
			("Inspected", "1", FINANCE),
		],
		"transitions": [
			("Draft", "Send for Inspection", "Pending Inspection", YARD, None),
			("Pending Inspection", "Pass Inspection", "Inspected", TECH, PASSED),
			("Pending Inspection", "Record Damage", "Damage Assessed", TECH, DAMAGED),
			("Damage Assessed", "Approve Charges", "Inspected", MANAGER, DAMAGED),
		],
	},
	DOWNTIME_WORKFLOW: {
		"document_type": "Rental Downtime Log",
		"states": [
			("Draft", "0", HIRE_DESK),
			("Pending", "0", MANAGER),
			("Approved", "1", MANAGER),
			("Rejected", "0", MANAGER),
		],
		"transitions": [
			("Draft", "Submit for Approval", "Pending", HIRE_DESK, None),
			("Pending", "Approve", "Approved", MANAGER, None),
			("Pending", "Reject", "Rejected", MANAGER, None),
		],
	},
}


def create_masters():
	for state, style in STATES:
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc({
				"doctype": "Workflow State", "workflow_state_name": state, "style": style,
			}).insert(ignore_permissions=True)

	for action in ACTIONS:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({
				"doctype": "Workflow Action Master", "workflow_action_name": action,
			}).insert(ignore_permissions=True)


def create_workflow():
	"""Create any missing workflow. Existing ones are left exactly as they are."""
	create_masters()
	created = []
	for name, spec in WORKFLOWS.items():
		if frappe.db.exists("Workflow", name) or not frappe.db.exists("DocType", spec["document_type"]):
			continue
		frappe.get_doc({
			"doctype": "Workflow",
			"workflow_name": name,
			"document_type": spec["document_type"],
			"workflow_state_field": "workflow_state",
			"is_active": 1,
			"send_email_alert": 0,
			"states": [{"state": s, "doc_status": d, "allow_edit": r} for s, d, r in spec["states"]],
			"transitions": [
				{"state": f, "action": a, "next_state": t, "allowed": r, "condition": c,
				 "allow_self_approval": 1}
				for f, a, t, r, c in spec["transitions"]
			],
		}).insert(ignore_permissions=True)
		created.append(name)
	frappe.db.commit()
	return created
