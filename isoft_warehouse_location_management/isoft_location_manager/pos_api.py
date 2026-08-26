# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt
#
# What POS Awesome needs from Isoft Location Manager.
#
# A cashier is never asked to choose a shelf — the location is decided by the same
# resolver the warehouse screens use, and arrives already filled in on the line. The
# item form can still be opened to change it, for the case where an assistant knows the
# stock has actually moved. Nothing appears in the item list: a till is not the place to
# read a stock report.
#
# Every function here is safe to call with the module switched off: it answers
# "nothing to show" rather than failing, so POS keeps working untouched.

import frappe
from frappe import _
from frappe.utils import cint, flt

from isoft_warehouse_location_management.isoft_location_manager.api import is_enabled

MAX_ITEMS = 2000


@frappe.whitelist()
def pos_enabled():
	"""One call the till makes on load to decide whether to show locations at all."""
	return {"enabled": bool(is_enabled("pos"))}


@frappe.whitelist()
def get_item_location_options(warehouse, item_code, qty=0, preferred=None):
	"""What the POS item form offers for one line.

	A default, the alternatives, and — when the line is bigger than one shelf holds —
	the plan for covering it. The cashier is never made to choose, but they should be
	able to see that a sale of 107 is coming off two shelves rather than one.
	"""
	if not is_enabled("pos") or not warehouse or not item_code:
		return {"enabled": 0, "default": None, "options": []}

	from isoft_warehouse_location_management.isoft_location_manager.location_resolver import resolve_one

	res = resolve_one(warehouse, item_code, "out", qty) or {}
	options = []
	for c in res.get("candidates") or []:
		options.append(
			{
				"value": c["location"],
				"qty": flt(c["qty"]),
				"is_unassigned": cint(c.get("is_unassigned")),
				"label": "{0} · {1}".format(
					_("Not put away") if c.get("is_unassigned") else c["location"],
					frappe.format_value(flt(c["qty"]), {"fieldtype": "Float"}),
				),
			}
		)
	from isoft_warehouse_location_management.isoft_location_manager.location_allocation import top_up

	chosen = preferred or res.get("location")
	plan, shortfall = top_up(warehouse, item_code, flt(qty), chosen) if flt(qty) > 0 else ([], 0)
	return {
		"enabled": 1,
		"default": res.get("location"),
		"mode": res.get("mode"),
		"reason": res.get("reason"),
		"options": options,
		# There is only something to divide when the goods are actually in more than one
		# place. With a single location holding the item the choice does not exist, and
		# the till should not offer one — a control that can only ever do nothing is
		# worse than no control.
		"can_split": 1 if len(options) > 1 else 0,
		# the whole proposal, one location or several — the till opens its pick table on
		# this, so a plan that only appeared for multi-location lines would leave the
		# ordinary case showing an empty table
		"plan": [{"location": p["location"], "qty": flt(p["qty"])} for p in plan],
		"shortfall": flt(shortfall),
	}
