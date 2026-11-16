# Copyright (c) 2026, ISOFT LDA
# For license information, please see license.txt

import frappe


def execute():
	"""Make browsers fetch the Item form script again.

	Desk caches a doctype's client scripts in the browser's localStorage keyed by
	DocType.modified and checks nothing else, so newly hooking a doctype_js onto Item
	reaches nobody who has already opened an Item on that browser. Moving the
	timestamp is what invalidates it.
	"""
	if not frappe.db.exists("DocType", "Item"):
		return
	frappe.db.set_value("DocType", "Item", "modified", frappe.utils.now(), update_modified=False)
	frappe.clear_cache(doctype="Item")
