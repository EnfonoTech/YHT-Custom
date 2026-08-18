# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

from frappe.model.document import Document


# Frappe derives the controller class name with a raw doctype.replace(" ", ""),
# NOT title-case — so "Mode of Payment" gives a lowercase "of" here, matching
# ERPNext's own ModeofPayment controller. Renaming this class breaks every save
# with ImportError.
class BranchConfigurationModeofPayment(Document):
	pass
