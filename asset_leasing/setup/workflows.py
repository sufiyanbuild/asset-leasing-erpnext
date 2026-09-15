"""Rental Agreement approval workflow (P2).

Only the approval decision lives in the workflow. The operational lifecycle -
Active, Partially Returned, Closed - is a separate read-only `status` field
driven by dispatch and return, because those are consequences of other
documents rather than human decisions.
"""

import frappe

WORKFLOW_NAME = "Rental Agreement Approval"

STATES = [
	("Draft", "Danger"),
	("Pending", "Warning"),
	("Approved", "Success"),
	("Rejected", "Danger"),
]

ACTIONS = ["Submit for Approval", "Approve", "Reject", "Revise"]

# state, docstatus, who may edit it
WORKFLOW_STATES = [
	("Draft", "0", "Leasing Hire Desk"),
	("Pending", "0", "Leasing Manager"),
	("Approved", "1", "Leasing Manager"),
	("Rejected", "0", "Leasing Hire Desk"),
]

# from, action, to, allowed role
TRANSITIONS = [
	("Draft", "Submit for Approval", "Pending", "Leasing Hire Desk"),
	("Pending", "Approve", "Approved", "Leasing Manager"),
	("Pending", "Reject", "Rejected", "Leasing Manager"),
	("Rejected", "Revise", "Draft", "Leasing Hire Desk"),
]


def create_workflow():
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

	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		return None

	frappe.get_doc({
		"doctype": "Workflow",
		"workflow_name": WORKFLOW_NAME,
		"document_type": "Rental Agreement",
		"workflow_state_field": "workflow_state",
		"is_active": 1,
		"send_email_alert": 0,
		"states": [
			{"state": s, "doc_status": d, "allow_edit": r} for s, d, r in WORKFLOW_STATES
		],
		"transitions": [
			{"state": f, "action": a, "next_state": t, "allowed": r}
			for f, a, t, r in TRANSITIONS
		],
	}).insert(ignore_permissions=True)
	frappe.db.commit()
	return WORKFLOW_NAME
