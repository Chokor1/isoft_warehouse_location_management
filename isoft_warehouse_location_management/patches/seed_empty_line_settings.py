# Copyright (c) 2026, ISOFT LDA
# For license information, please see license.txt

import frappe


def execute():
	"""Give the two new switches their documented values on a site that already exists.

	A field default applies when a document is created, and a Single that is already
	there is never created again — so adding `show_empty_lines` with default 1 to
	Picking Settings leaves the stored value at 0 the first time anything saves it, and
	every Locations board would quietly stop showing the lines that have run to zero.
	Nobody can have switched these off on purpose yet: they did not exist until now.
	"""
	for field, value in (("show_empty_lines", "1"), ("remove_empty_lines", "0")):
		if frappe.db.sql(
			"select 1 from tabSingles where doctype = 'Picking Settings' and field = %s", field
		):
			frappe.db.sql(
				"update tabSingles set value = %s where doctype = 'Picking Settings' and field = %s",
				(value, field),
			)
		else:
			frappe.db.sql(
				"insert into tabSingles (doctype, field, value) values ('Picking Settings', %s, %s)",
				(field, value),
			)
	frappe.clear_cache()
