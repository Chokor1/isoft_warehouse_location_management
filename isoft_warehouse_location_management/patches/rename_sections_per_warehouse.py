# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
#
# Warehouse Location used to be named by its bare code, which made codes globally
# unique — the second shop that wanted an "A-01" silently could not have one.
# Locations are now named `<warehouse prefix>-<code>`, so every warehouse can label
# its racking the way the racking is actually labelled.

import frappe

from isoft_warehouse_location_management.isoft_location_manager.doctype.warehouse_location.warehouse_location import (
	warehouse_prefix,
)


def execute():
	frappe.reload_doc("isoft_warehouse_location_management", "doctype", "warehouse_location")
	frappe.reload_doc("isoft_warehouse_location_management", "doctype", "item_default_location")
	frappe.reload_doc("isoft_warehouse_location_management", "doctype", "location_stock")

	# the prefix is cached on the Warehouse, so its custom field has to exist first
	from isoft_warehouse_location_management.isoft_location_manager.install import create_custom_fields

	create_custom_fields()

	_drop_legacy_unique_code()

	for row in frappe.get_all(
		"Warehouse Location", fields=["name", "location_code", "warehouse"], order_by="creation asc"
	):
		if not row.warehouse:
			continue
		code = (row.location_code or row.name).strip().upper()
		prefix = warehouse_prefix(row.warehouse)
		target = "{0}-{1}".format(prefix, code)

		frappe.db.set_value(
			"Warehouse Location",
			row.name,
			{"location_code": code, "warehouse_prefix": prefix},
			update_modified=False,
		)
		if row.name == target:
			continue
		if frappe.db.exists("Warehouse Location", target):
			frappe.log_error(
				message="Cannot rename {0} to {1}: target already exists".format(row.name, target),
				title="Isoft Location Manager location rename",
			)
			continue
		# rename_doc rewrites every Link field pointing here, custom fields included
		frappe.rename_doc("Warehouse Location", row.name, target, force=True, show_alert=False)

	frappe.db.commit()

	from isoft_warehouse_location_management.isoft_location_manager.install import ensure_indexes, ensure_unassigned_locations

	ensure_indexes()
	created = ensure_unassigned_locations()
	if created:
		print("Isoft Location Manager: created {0} unassigned-stock location(s)".format(len(created)))
	frappe.db.commit()


def _drop_legacy_unique_code():
	"""`location_code` carried a UNIQUE index; uniqueness is now per warehouse."""
	for idx in frappe.db.sql("show index from `tabWarehouse Location`", as_dict=True):
		if idx.get("Column_name") == "location_code" and not idx.get("Non_unique"):
			try:
				frappe.db.sql("alter table `tabWarehouse Location` drop index `{0}`".format(idx["Key_name"]))
			except Exception:
				frappe.log_error(title="Isoft Location Manager: dropping location_code unique index failed")
