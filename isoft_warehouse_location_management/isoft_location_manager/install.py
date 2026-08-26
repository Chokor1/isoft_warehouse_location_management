# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt

import frappe

ROLES = ["Location Manager"]


def after_install():
	create_roles()
	create_print_formats()
	ensure_settings()
	create_custom_fields()
	ensure_indexes()
	ensure_unassigned_locations()
	frappe.db.commit()


def create_custom_fields():
	"""Location pickers on stock documents, plus the item's declared home locations."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(
		{
			"Stock Entry Detail": [
				{
					"fieldname": "custom_from_location",
					"label": "From Location (Picking)",
					"fieldtype": "Link",
					"options": "Warehouse Location",
					"insert_after": "s_warehouse",
					"depends_on": "eval:doc.s_warehouse",
					# Kept for everything that reads a single location off the row, but not
					# shown: "Picked From Location" below says the same thing and copes with
					# a line that came off several places. Two fields for one fact is worse
					# than one, and they can disagree.
					"hidden": 1,
				},
				{
					"fieldname": "custom_to_location",
					"label": "To Location (Picking)",
					"fieldtype": "Link",
					"options": "Warehouse Location",
					"insert_after": "t_warehouse",
					"depends_on": "eval:doc.t_warehouse",
				},
				{
					"fieldname": "custom_location_allocation",
					"label": "Picked From Location",
					"fieldtype": "Small Text",
					"insert_after": "custom_from_location",
					"read_only": 1,
					"no_copy": 1,
					# shown in the grid because the column *is* the control: clicking it opens
					# the divide dialog, which is one click instead of expanding the row first
					"in_list_view": 1,
					"columns": 2,
					"description": "Where this line was picked from. One location, or several when it spans more than one — the line itself is never split.",
				},
			],
			"Warehouse": [
				{
					"fieldname": "custom_location_prefix",
					"label": "Location Prefix",
					"fieldtype": "Data",
					"insert_after": "warehouse_name",
					"read_only": 1,
					"allow_on_submit": 0,
					"description": "Prefix used to name this warehouse's locations. Set automatically.",
				}
			],
			# Incoming goods: an optional put-away location. A line left blank simply
			# lands in unassigned stock, which is a true answer, so nothing here is reqd.
			"Purchase Receipt Item": [
				{
					"fieldname": "custom_to_location",
					"label": "Put Away In",
					"fieldtype": "Link",
					"options": "Warehouse Location",
					"insert_after": "warehouse",
					"depends_on": "eval:doc.warehouse",
					"in_list_view": 1,
					"columns": 2,
					"description": "Optional. Leave it blank and the goods stay in unassigned stock.",
				},
			],
			"Purchase Invoice Item": [
				{
					"fieldname": "custom_to_location",
					"label": "Put Away In",
					"fieldtype": "Link",
					"options": "Warehouse Location",
					"insert_after": "warehouse",
					"depends_on": "eval:parent.update_stock && doc.warehouse",
					"in_list_view": 1,
					"columns": 2,
					"description": "Optional, and only used when the invoice updates stock.",
				},
			],
			"Delivery Note Item": [
				{
					"fieldname": "custom_from_location",
					"label": "Picked From Location (internal)",
					"fieldtype": "Link",
					"options": "Warehouse Location",
					"insert_after": "warehouse",
					"depends_on": "eval:doc.warehouse",
					"hidden": 1,
					"description": "Superseded by Picked From Location. Kept so anything reading a single value still finds one.",
				},
				{
					"fieldname": "custom_location_allocation",
					"label": "Picked From Location",
					"fieldtype": "Small Text",
					"insert_after": "custom_from_location",
					"read_only": 1,
					"no_copy": 1,
					# shown in the grid because the column *is* the control: clicking it opens
					# the divide dialog, which is one click instead of expanding the row first
					"in_list_view": 1,
					"columns": 2,
					"description": "Where this line was picked from. One location, or several when it spans more than one — the line itself is never split.",
				},
			],
			"Sales Invoice Item": [
				{
					"fieldname": "custom_from_location",
					"label": "Picked From Location (internal)",
					"fieldtype": "Link",
					"options": "Warehouse Location",
					"insert_after": "warehouse",
					"depends_on": "eval:parent.update_stock && doc.warehouse",
					"hidden": 1,
					"description": "Superseded by Picked From Location. Kept so anything reading a single value still finds one.",
				},
				{
					"fieldname": "custom_location_allocation",
					"label": "Picked From Location",
					"fieldtype": "Small Text",
					"insert_after": "custom_from_location",
					"read_only": 1,
					"no_copy": 1,
					# shown in the grid because the column *is* the control: clicking it opens
					# the divide dialog, which is one click instead of expanding the row first
					"in_list_view": 1,
					"columns": 2,
					"description": "Where this line was picked from. One location, or several when it spans more than one — the line itself is never split.",
				},
			],
			"Item": [
				{
					"fieldname": "custom_picking_location_break",
					"label": "Warehouse Locations",
					"fieldtype": "Section Break",
					"insert_after": "item_defaults",
					"collapsible": 1,
				},
				{
					"fieldname": "custom_default_locations",
					"label": "Default Locations",
					"fieldtype": "Table",
					"options": "Item Default Location",
					"insert_after": "custom_picking_location_break",
					"description": "Where this item is put away in each warehouse. Overrides every other put-away rule.",
				},
			],
		},
		ignore_validate=True,
	)


def ensure_indexes():
	"""One balance row per (warehouse, location, item) — and make the lookups fast.

	`tabLocation Stock` shipped with no index beyond the primary key, so every resolver
	read was a table scan and nothing stopped duplicate balance rows.
	"""
	_dedupe_location_stock()
	try:
		if not frappe.db.has_index("tabLocation Stock", "unique_location_item"):
			frappe.db.add_unique("Location Stock", ["warehouse", "location", "item_code"], "unique_location_item")
	except Exception:
		frappe.log_error(title="Isoft Location Manager: Location Stock unique index failed")

	try:
		if not frappe.db.has_index("tabLocation Stock", "wh_item_index"):
			frappe.db.add_index("Location Stock", ["warehouse", "item_code"], "wh_item_index")
	except Exception:
		frappe.log_error(title="Isoft Location Manager: Location Stock index failed")

	_clean_warehouse_location_table()



def _clean_warehouse_location_table():
	"""Location codes are unique per warehouse now, not across the whole system."""
	# an early build of this doctype had a `location` field; it survived as a dead column
	# carrying a UNIQUE index, which is a trap for anything that ever writes to it
	columns = [c[0] for c in frappe.db.sql("show columns from `tabWarehouse Location`")]
	if "location" in columns:
		orphans = frappe.db.sql(
			"select count(*) from `tabWarehouse Location` where `location` is not null"
		)[0][0]
		if not orphans:
			try:
				frappe.db.sql("alter table `tabWarehouse Location` drop column `location`")
			except Exception:
				frappe.log_error(title="Isoft Location Manager: dropping dead location column failed")

	try:
		if not frappe.db.has_index("tabWarehouse Location", "unique_warehouse_code"):
			frappe.db.add_unique(
				"Warehouse Location", ["warehouse", "location_code"], "unique_warehouse_code"
			)
	except Exception:
		frappe.log_error(title="Isoft Location Manager: Warehouse Location unique index failed")


def _dedupe_location_stock():
	"""Collapse any duplicate balance rows before the unique index goes on."""
	dupes = frappe.db.sql(
		"""select warehouse, location, item_code, count(*) n
		from `tabLocation Stock`
		group by warehouse, location, item_code having n > 1""",
		as_dict=True,
	)
	for d in dupes:
		rows = frappe.get_all(
			"Location Stock",
			filters={"warehouse": d.warehouse, "location": d.location, "item_code": d.item_code},
			fields=["name", "qty"],
			order_by="creation asc",
		)
		total = sum(frappe.utils.flt(r.qty) for r in rows)
		frappe.db.set_value("Location Stock", rows[0].name, "qty", total, update_modified=False)
		for r in rows[1:]:
			frappe.db.delete("Location Stock", {"name": r.name})


def ensure_unassigned_locations():
	"""Every leaf warehouse gets its Unassigned Stock location.

	Nothing is copied into it: its quantity is `Bin.actual_qty` minus whatever the real
	locations hold, so from the moment this runs every unit already in stock is
	accounted for and can be put away.
	"""
	from isoft_warehouse_location_management.isoft_location_manager.doctype.warehouse_location.warehouse_location import (
		ensure_all_unassigned_locations,
	)

	return ensure_all_unassigned_locations()


def create_print_formats():
	"""One Picking Sheet per document that can be picked from.

	Print Format names are unique across the site, so the doctype is part of the name;
	the button that opens them just says "Picking Sheet".
	"""
	import os

	from isoft_warehouse_location_management.isoft_location_manager.picking_sheet import FORMAT_FOR

	html = open(
		os.path.join(os.path.dirname(os.path.abspath(__file__)), "picking_sheet.html"),
		encoding="utf-8",
	).read()

	fields = {
		"doc_type": None,
		"module": "Isoft Location Manager",
		"standard": "No",
		"custom_format": 1,
		"print_format_type": "Jinja",
		"disabled": 0,
		"html": html,
	}
	for doctype, name in FORMAT_FOR.items():
		values = dict(fields, doc_type=doctype)
		if frappe.db.exists("Print Format", name):
			doc = frappe.get_doc("Print Format", name)
			doc.update(values)
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)
		else:
			doc = frappe.new_doc("Print Format")
			doc.update(values)
			doc.name = name
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)


def create_roles():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc(
				{
					"doctype": "Role",
					"role_name": role,
					"desk_access": 1,
				}
			).insert(ignore_permissions=True)


SETTING_DEFAULTS = {
	"stock_validation": "Block",
	"enabled": 1,
	"enable_stock_entry": 1,
	"enable_delivery_note": 1,
	"enable_pos": 1,
	"auto_resolve_locations": 1,
	"allow_pick_from_unassigned": 1,
}


def ensure_settings():
	"""Materialise the Single, and write the defaults for any flag never saved.

	An absent Check row reads back as 0, so a flag that has never been touched would
	otherwise look switched off on the settings screen.
	"""
	doc = frappe.get_single("Picking Settings")
	stored = {
		r[0]
		for r in frappe.db.sql("select field from tabSingles where doctype = 'Picking Settings'")
	}
	for field, value in SETTING_DEFAULTS.items():
		if field not in stored:
			doc.set(field, value)
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)


# Kept for the old hook name used by existing installs.
create_custom_fields_for_stock_entry = create_custom_fields
