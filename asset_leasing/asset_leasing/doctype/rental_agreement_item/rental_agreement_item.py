"""One machine on a hire agreement.

All validation lives on the parent (rental_agreement.py) because the rules are
cross-row - duplicate detection and availability both need to see every line and
the agreement's period. A child controller cannot see its siblings reliably.
"""

from frappe.model.document import Document


class RentalAgreementItem(Document):
	pass
