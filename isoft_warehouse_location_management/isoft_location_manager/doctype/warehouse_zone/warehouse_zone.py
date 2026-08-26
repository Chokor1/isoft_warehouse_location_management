# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt
#
# A Warehouse Zone groups the locations of one warehouse: an aisle, a cold room, a
# mezzanine, a returns corner. It is an organising layer only — stock never lives in a
# zone, it lives in a location. Nothing about picking changes when zones are introduced,
# so a warehouse that ignores them behaves exactly as before.

import frappe
from frappe import _
from frappe.model.document import Document

from isoft_warehouse_location_management.isoft_location_manager.doctype.warehouse_location.warehouse_location import (
	warehouse_prefix,
)


class WarehouseZone(Document):
	def autoname(self):
		"""Name zones per warehouse: `<warehouse prefix>-Z-<zone code>`.

		Zone codes are only unique inside their warehouse — two shops may both call an
		aisle "FRONT" — and the `-Z-` keeps a zone from ever colliding with a location
		name built from the same prefix.
		"""
		code = (self.zone_code or "").strip().upper()
		if not code:
			frappe.throw(_("Zone Code is required."))
		self.zone_code = code
		if not self.warehouse:
			frappe.throw(_("Warehouse is required."))
		self.warehouse_prefix = warehouse_prefix(self.warehouse)
		self.name = "{0}-Z-{1}".format(self.warehouse_prefix, code)

	def validate(self):
		if self.warehouse and frappe.get_cached_value("Warehouse", self.warehouse, "is_group"):
			frappe.throw(
				_("Warehouse {0} is a group warehouse. Zones must belong to a leaf warehouse.").format(
					self.warehouse
				)
			)
		self.zone_code = (self.zone_code or "").strip().upper()
		if not self.zone_name:
			self.zone_name = self.zone_code.title()
		if not self.warehouse_prefix:
			self.warehouse_prefix = warehouse_prefix(self.warehouse)

		# autoname has already run by the time validate is called, so a duplicate code
		# has *become* a duplicate name — excluding self.name would hide exactly the
		# clash being looked for, and the insert would fail with a raw database error.
		clash = frappe.db.get_value(
			"Warehouse Zone",
			{"warehouse": self.warehouse, "zone_code": self.zone_code}
			if self.is_new()
			else {"warehouse": self.warehouse, "zone_code": self.zone_code, "name": ["!=", self.name]},
			"name",
		)
		if clash:
			frappe.throw(
				_("Zone code {0} is already used in {1} by {2}.").format(
					self.zone_code, self.warehouse, clash
				),
				frappe.DuplicateEntryError,
			)

	def on_trash(self):
		"""Deleting a zone only unfiles its locations — it never touches stock."""
		frappe.db.sql(
			"update `tabWarehouse Location` set zone=null where zone=%s", self.name
		)


def zones_of(warehouse, active_only=True):
	"""Zones of one warehouse, in display order."""
	filters = {"warehouse": warehouse}
	if active_only:
		filters["is_active"] = 1
	return frappe.get_all(
		"Warehouse Zone",
		filters=filters,
		fields=["name", "zone_code", "zone_name", "warehouse", "sequence", "description", "is_active"],
		order_by="sequence asc, zone_code asc",
		limit_page_length=0,
	)
