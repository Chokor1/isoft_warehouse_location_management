# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
#
# First half of the Section -> Location rename: the doctypes themselves.
#
# This runs BEFORE the model sync. If it did not, the sync would read the new doctype
# JSON, find no matching records, and build a second empty set of doctypes beside the
# real data. The *fields* are handled after the sync instead — see
# `backfill_location_fields`, which explains why they cannot be done here.
#
# ERPNext already owns a doctype called `Location` (asset locations), so these are
# `Warehouse Location` and friends, which is the clearer name anyway.

import frappe

DOCTYPES = [
	("Warehouse Section", "Warehouse Location"),
	("Section Stock", "Location Stock"),
	("Section Stock Movement Item", "Location Stock Movement Item"),
	("Section Stock Movement", "Location Stock Movement"),
	("Item Default Section", "Item Default Location"),
]


def execute():
	if not frappe.db.exists("DocType", "Warehouse Section"):
		return  # fresh install: nothing to carry over

	for old, new in DOCTYPES:
		_rename_doctype(old, new)

	_relabel_logs()
	frappe.clear_cache()
	frappe.db.commit()
	print("Isoft Location Manager: sections are now locations")


def _rename_doctype(old, new):
	if not frappe.db.exists("DocType", old) or frappe.db.exists("DocType", new):
		return
	frappe.rename_doc("DocType", old, new, force=True, ignore_permissions=True, show_alert=False)
	# Link and Table fields in this app's own JSON are about to be rewritten by the sync,
	# but anything pointing here from elsewhere is ours to fix
	frappe.db.sql("update `tabCustom Field` set options = %s where options = %s", (new, old))
	frappe.db.sql("update `tabDocField` set options = %s where options = %s", (new, old))


def _relabel_logs():
	"""The activity log's category was a Select with "Section" among its options."""
	if frappe.db.exists("DocType", "Picking Log"):
		frappe.db.sql("update `tabPicking Log` set category = 'Location' where category = 'Section'")
