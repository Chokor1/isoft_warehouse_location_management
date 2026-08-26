# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
#
# Isoft Location Manager used to keep its own list of who was a Requester and who was a Keeper,
# and reconcile it into Has Role on save. That was a second place to forget: roles are
# assigned on the User like every other role, and what a user sees comes from their
# ERPNext User Permissions narrowed to the enabled warehouses.
#
# The roles themselves are left exactly as they are — this only removes the table that
# used to mirror them.

import frappe


def execute():
	for field in ("requester_users", "preparer_users"):
		frappe.db.sql(
			"delete from `tabPicking Role User` where parent = 'Picking Settings' and parentfield = %s",
			field,
		)

	if frappe.db.exists("DocType", "Picking Role User") and not frappe.db.count("Picking Role User"):
		frappe.delete_doc("DocType", "Picking Role User", ignore_permissions=True, force=True)
		print("Isoft Location Manager: role membership is now roles + user permissions")
	frappe.db.commit()
