# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt
#
# Access is not configured here.
#
# Who may open Isoft Location Manager is the Location Manager role,
# assigned on the User like any other role. What they may see is their ERPNext User
# Permissions for Warehouse, narrowed to the warehouses enabled in this Single. Keeping
# a second list of users here only ever meant two places to forget.

import frappe
from frappe.model.document import Document


class PickingSettings(Document):
	def on_update(self):
		# the module switch is cached per request; a save has to invalidate it
		frappe.local.isoft_warehouse_location_management_settings = {}
