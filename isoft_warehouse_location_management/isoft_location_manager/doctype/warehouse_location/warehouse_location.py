# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt
#
# A Warehouse Location is a physical sub-location of a leaf warehouse.
#
# Every warehouse also owns exactly one *system* location — the Unassigned Stock
# location. It is never stored in the Location Stock ledger: its quantity is always
# derived as `Bin.actual_qty - sum(real location balances)`. That means the day this
# app is installed, every unit already in the warehouse is accounted for (it is all
# "unassigned"), and putting stock away is simply a transfer out of it.

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

UNASSIGNED_CODE = "UNASSIGNED"
UNASSIGNED_LABEL = "Unassigned Stock"
UNASSIGNED_PRIORITY = 900  # picked last — real locations always win


class WarehouseLocation(Document):
	def autoname(self):
		"""Name locations per warehouse: `<warehouse prefix>-<location code>`.

		Location codes are only unique inside their warehouse, so two shops can both
		label a rack "A-01" and still get distinct records.
		"""
		code = (self.location_code or "").strip().upper()
		if not code:
			frappe.throw(_("Location Code is required."))
		self.location_code = code
		if not self.warehouse:
			frappe.throw(_("Warehouse is required."))
		self.warehouse_prefix = warehouse_prefix(self.warehouse)
		self.name = "{0}-{1}".format(self.warehouse_prefix, code)

	def validate(self):
		if self.warehouse and frappe.get_cached_value("Warehouse", self.warehouse, "is_group"):
			frappe.throw(
				_("Warehouse {0} is a group warehouse. Locations must belong to a leaf warehouse.").format(
					self.warehouse
				)
			)

		self.location_code = (self.location_code or "").strip().upper()
		if not self.warehouse_prefix:
			self.warehouse_prefix = warehouse_prefix(self.warehouse)

		self._validate_unique_code()
		self._validate_unassigned()
		self._validate_single_default_receiving()
		self._validate_zone()

	def on_trash(self):
		# The unassigned location is made with its warehouse and goes with it. On its own it
		# cannot be deleted: the ledger measures unassigned stock against it.
		if self.is_unassigned and frappe.flags.get("ip_deleting_warehouse") != self.warehouse:
			frappe.throw(
				_("{0} is the system location of {1}: it is created with the warehouse and is "
				  "deleted with it. Deactivate the warehouse, or delete the warehouse itself.").format(
					self.name, self.warehouse
				)
			)
		if frappe.db.exists("Location Stock", {"location": self.name, "qty": [">", 0]}):
			frappe.throw(_("Location {0} still holds stock. Move it out before deleting.").format(self.name))

	# ------------------------------------------------------------------
	def _validate_zone(self):
		"""A zone groups locations of one warehouse, so it cannot reach across warehouses."""
		if not self.zone:
			return
		zone_wh = frappe.db.get_value("Warehouse Zone", self.zone, "warehouse")
		if zone_wh != self.warehouse:
			frappe.throw(
				_("Zone {0} belongs to {1}, not to {2}.").format(self.zone, zone_wh, self.warehouse)
			)

	def _validate_unique_code(self):
		clash = frappe.db.get_value(
			"Warehouse Location",
			{"warehouse": self.warehouse, "location_code": self.location_code, "name": ["!=", self.name]},
			"name",
		)
		if clash:
			frappe.throw(
				_("Location code {0} is already used in warehouse {1} ({2}).").format(
					self.location_code, self.warehouse, clash
				)
			)

	def _validate_unassigned(self):
		if self.is_unassigned:
			self.location_type = "Unassigned"
			self.is_active = 1
			self.is_default_receiving = 0
			self.pick_priority = UNASSIGNED_PRIORITY
			other = frappe.db.get_value(
				"Warehouse Location",
				{"warehouse": self.warehouse, "is_unassigned": 1, "name": ["!=", self.name]},
				"name",
			)
			if other:
				frappe.throw(
					_("Warehouse {0} already has an unassigned-stock location ({1}).").format(
						self.warehouse, other
					)
				)
		elif self.location_type == "Unassigned":
			frappe.throw(
				_("Only the system location may use the Unassigned type. Pick another Location Type.")
			)

	def _validate_single_default_receiving(self):
		if not self.is_default_receiving:
			return
		frappe.db.sql(
			"""update `tabWarehouse Location` set is_default_receiving = 0
			where warehouse = %s and name != %s and is_default_receiving = 1""",
			(self.warehouse, self.name),
		)


# ======================================================================
# warehouse prefix
# ======================================================================
def warehouse_prefix(warehouse):
	"""A short, stable, unique code for a warehouse, used to name its locations.

	Warehouses here are named like "02 - Loja Viana - ITEC", so the leading token is
	already the code the business uses. Anything else falls back to initials.
	"""
	cached = frappe.db.get_value("Warehouse", warehouse, "custom_location_prefix")
	if cached:
		return cached

	prefix = _build_prefix(warehouse)
	taken = set(
		frappe.get_all(
			"Warehouse",
			filters={"custom_location_prefix": ["!=", ""], "name": ["!=", warehouse]},
			pluck="custom_location_prefix",
		)
	)
	candidate, n = prefix, 1
	while candidate in taken:
		n += 1
		candidate = "{0}{1}".format(prefix, n)

	frappe.db.set_value("Warehouse", warehouse, "custom_location_prefix", candidate, update_modified=False)
	return candidate


def _build_prefix(warehouse):
	name = frappe.db.get_value("Warehouse", warehouse, "warehouse_name") or warehouse
	head = name.split(" - ")[0].strip()
	clean = re.sub(r"[^A-Za-z0-9]", "", head).upper()
	if clean and len(clean) <= 6:
		return clean
	# initials of the words, e.g. "Devoluções Alvalade" -> "DA"
	initials = "".join(w[0] for w in re.split(r"[\s\-_/]+", head) if w)
	initials = re.sub(r"[^A-Za-z0-9]", "", initials).upper()
	return (initials or clean or "WH")[:6]


# ======================================================================
# unassigned-stock location registry
# ======================================================================
def get_unassigned_location(warehouse, create=True):
	"""The warehouse's unassigned-stock location, creating it on first use."""
	if not warehouse:
		return None
	name = frappe.db.get_value("Warehouse Location", {"warehouse": warehouse, "is_unassigned": 1}, "name")
	if name or not create:
		return name
	if frappe.get_cached_value("Warehouse", warehouse, "is_group"):
		return None
	return ensure_unassigned_location(warehouse)


def ensure_unassigned_location(warehouse):
	doc = frappe.get_doc(
		{
			"doctype": "Warehouse Location",
			"location_code": UNASSIGNED_CODE,
			"location_name": UNASSIGNED_LABEL,
			"warehouse": warehouse,
			"location_type": "Unassigned",
			"is_unassigned": 1,
			"is_active": 1,
			"pick_priority": UNASSIGNED_PRIORITY,
			"description": _(
				"Stock physically in this warehouse that has not been put away into a location yet. "
				"Its quantity is calculated, not stored."
			),
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


def unassigned_location_names():
	"""Every unassigned location in the system (cheap set membership test)."""
	return set(frappe.get_all("Warehouse Location", filters={"is_unassigned": 1}, pluck="name"))


def is_unassigned(location):
	if not location:
		return False
	return bool(frappe.db.get_value("Warehouse Location", location, "is_unassigned"))


def ensure_all_unassigned_locations(warehouses=None):
	"""Create the unassigned location for every leaf warehouse that lacks one."""
	if warehouses is None:
		warehouses = frappe.get_all("Warehouse", filters={"is_group": 0}, pluck="name")
	created = []
	for wh in warehouses:
		if not frappe.db.get_value("Warehouse Location", {"warehouse": wh, "is_unassigned": 1}, "name"):
			created.append(ensure_unassigned_location(wh))
	return created


def on_warehouse_trash(doc, method=None):
	"""Clear this app's own records out of the way when a warehouse is deleted.

	Every warehouse is given an unassigned location the moment it is created, and that
	location links straight back to it. Without this the app made every warehouse
	undeletable from the day it was made — including one that never held anything.

	Only what is derived from the warehouse goes with it: its locations, its zones, its
	rows in the settings, and its activity log. Anything that records something that
	happened — stock sitting on a location, a movement, a count, a stocktake — stops the
	deletion and is named, because deleting the warehouse must not quietly delete the
	history of what went through it.
	"""
	warehouse = doc.name

	for doctype, label in (
		("Location Stock Movement", _("location movement")),
		("Location Inventory", _("location count")),
		("Warehouse Inventory", _("stocktake")),
	):
		names = frappe.get_all(doctype, filters={"warehouse": warehouse}, pluck="name", limit=4)
		if names:
			frappe.throw(
				_("{0} has {1} {2}(s) recorded against it, such as {3}. They are the record of what "
				  "happened there, so they do not go with the warehouse. Deactivate it instead, or "
				  "remove those first.").format(
					warehouse, frappe.db.count(doctype, {"warehouse": warehouse}), label, ", ".join(names)
				),
				title=_("Warehouse Has History"),
			)

	held = frappe.db.sql(
		"""select ls.item_code, ls.qty, wl.location_code
		   from `tabLocation Stock` ls
		   join `tabWarehouse Location` wl on wl.name = ls.location
		   where ls.warehouse = %s and ls.qty != 0
		   order by abs(ls.qty) desc limit 5""",
		(warehouse,),
	)
	if held:
		frappe.throw(
			_("{0} still has stock on its locations: {1}. Take it off them first.").format(
				warehouse, "; ".join("%s on %s (%s)" % (i, c, flt(q)) for i, q, c in held)
			),
			title=_("Locations Still Hold Stock"),
		)

	# Derived rows go first, so nothing is left pointing at a location about to be removed.
	for table in ("Location Stock", "Item Default Location", "Picking Warehouse", "Picking Log"):
		frappe.db.sql("delete from `tab{0}` where warehouse = %s".format(table), (warehouse,))

	if frappe.db.get_single_value("Picking Settings", "default_warehouse") == warehouse:
		frappe.db.set_value("Picking Settings", "Picking Settings", "default_warehouse", None)

	for zone in frappe.get_all("Warehouse Zone", filters={"warehouse": warehouse}, pluck="name"):
		frappe.delete_doc("Warehouse Zone", zone, ignore_permissions=True)

	# The flag is what lets the system location go: only while its own warehouse is going.
	frappe.flags.ip_deleting_warehouse = warehouse
	try:
		for loc in frappe.get_all(
			"Warehouse Location", filters={"warehouse": warehouse},
			fields=["name", "is_unassigned"], order_by="is_unassigned asc",
		):
			frappe.delete_doc("Warehouse Location", loc.name, ignore_permissions=True)
	finally:
		frappe.flags.ip_deleting_warehouse = None


def on_warehouse_insert(doc, method=None):
	"""Hooked on Warehouse: a new leaf warehouse gets its unassigned location at once."""
	if doc.is_group:
		return
	try:
		get_unassigned_location(doc.name)
	except Exception:
		frappe.log_error(title="Isoft Location Manager: unassigned location creation failed")
