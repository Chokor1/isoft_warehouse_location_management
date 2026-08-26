# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate


# ======================================================================
# module switch
# ======================================================================
# Every entry point into this app asks here first. With the module off nothing is
# validated, nothing is mirrored, no field is required and no screen offers a location
# — the stored location data simply sits there until it is switched back on.

FEATURE_FIELDS = {
	"stock_entry": "enable_stock_entry",
	"delivery_note": "enable_delivery_note",
	"pos": "enable_pos",
	"purchase": "enable_purchase",
}

SETTING_DEFAULTS = {
	"enabled": True,
	"enable_stock_entry": True,
	"enable_delivery_note": True,
	"enable_pos": True,
	"auto_resolve_locations": True,
	"allow_pick_from_unassigned": True,
	"require_location_on_out": True,
	"enable_purchase": True,
}


def setting(fieldname, default=None):
	"""Read a Picking Settings flag.

	`get_single_value` casts a missing Check row to 0, which is indistinguishable from
	"switched off", so the row's existence is checked directly and the documented
	default applies when it has never been saved.
	"""
	if default is None:
		default = SETTING_DEFAULTS.get(fieldname, False)
	cache = frappe.local.isoft_warehouse_location_management_settings = getattr(
		frappe.local, "isoft_warehouse_location_management_settings", {}
	)
	if fieldname in cache:
		return cache[fieldname]

	rows = frappe.db.sql(
		"select value from tabSingles where doctype = 'Picking Settings' and field = %s", fieldname
	)
	value = default if not rows else bool(cint(rows[0][0]))
	cache[fieldname] = value
	return value


def is_enabled(feature=None):
	"""Is the module on — and, optionally, this particular integration?"""
	if not setting("enabled"):
		return False
	if not feature:
		return True
	field = FEATURE_FIELDS.get(feature)
	return setting(field) if field else True


@frappe.whitelist()
def module_status():
	"""What the desk should show. Safe to call with the module off."""
	return {
		"enabled": is_enabled(),
		"stock_entry": is_enabled("stock_entry"),
		"delivery_note": is_enabled("delivery_note"),
		"pos": is_enabled("pos"),
		"purchase": is_enabled("purchase"),
	}


def require_enabled(what=None):
	if is_enabled():
		return
	frappe.throw(
		_("Isoft Location Manager is switched off. Turn it back on in Picking Settings to {0}.").format(
			what or _("use this")
		),
		title=_("Module Disabled"),
	)


def _wh_descendants(warehouse):
	node = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt"], as_dict=True)
	if not node or node.lft is None:
		return {warehouse}
	names = frappe.get_all(
		"Warehouse", filters={"lft": [">=", node.lft], "rgt": ["<=", node.rgt]}, pluck="name"
	)
	return set(names) | {warehouse}


def enabled_warehouse_set():
	"""Warehouses enabled for Isoft Location Manager (incl. children). None => all enabled (empty table)."""
	rows = frappe.get_all(
		"Picking Warehouse",
		filters={"parenttype": "Picking Settings", "parentfield": "enabled_warehouses"},
		pluck="warehouse",
	)
	if not rows:
		return None
	out = set()
	for wh in rows:
		out |= _wh_descendants(wh)
	return out


def is_warehouse_enabled(warehouse):
	if not warehouse:
		return False
	s = enabled_warehouse_set()
	return True if s is None else warehouse in s


@frappe.whitelist()
def get_enabled_warehouses():
	"""List of enabled warehouse names (with children). Empty list means 'all enabled'."""
	s = enabled_warehouse_set()
	return sorted(s) if s is not None else []


def log_activity(category, action, reference_name=None, message=None, warehouse=None, reference_type=None):
	"""Append an audit entry to Picking Log. Never breaks the calling flow."""
	try:
		frappe.get_doc(
			{
				"doctype": "Picking Log",
				"activity_datetime": frappe.utils.now_datetime(),
				"user": frappe.session.user,
				"category": category,
				"action": action,
				"reference_type": reference_type,
				"reference_name": reference_name,
				"warehouse": warehouse,
				"message": message,
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="Picking Log write failed")
