# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt
#
# A Warehouse Inventory is a stocktake of one warehouse, taken location by location.
#
# It holds no quantities of its own. Each location is counted with a Location Inventory
# that points back here and posts its own reconciliation. From those counts the
# inventory knows which locations are done, which are being counted, and which are
# still waiting. Nothing is copied into it that could fall out of step: the counters on
# the document exist for lists, and are recomputed from the counts whenever one changes.

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime

from isoft_warehouse_location_management.isoft_location_manager.api import (
	is_warehouse_enabled,
	log_activity,
	natural_key,
	require_enabled,
)


class WarehouseInventory(Document):
	def validate(self):
		if self.is_new():
			require_enabled(_("take stock of a warehouse"))
			self.status = "Open"
			self.started_on = now_datetime()
			self.started_by = frappe.session.user
		self._check_warehouse()
		if self.status == "Open":
			# One open stocktake per warehouse, so that done always means done in this one.
			other = frappe.db.get_value(
				"Warehouse Inventory",
				{"warehouse": self.warehouse, "status": "Open", "name": ("!=", self.name or "")},
				"name",
			)
			if other:
				frappe.throw(
					_("{0} already has an open inventory, {1}. Complete it before starting another, "
					  "so that a location marked done means done in one stocktake.").format(self.warehouse, other),
					title=_("Inventory Already Open"),
				)

	def _check_warehouse(self):
		wh = frappe.db.get_value("Warehouse", self.warehouse, ["company", "is_group"], as_dict=True)
		if not wh:
			frappe.throw(_("Warehouse {0} does not exist.").format(self.warehouse))
		if wh.is_group:
			frappe.throw(
				_("{0} is a group. Take stock of the warehouses under it, one at a time.").format(self.warehouse)
			)
		if not is_warehouse_enabled(self.warehouse):
			frappe.throw(_("{0} is not enabled in Isoft Location Manager.").format(self.warehouse))
		if self.is_new() and not frappe.db.count(
			"Warehouse Location", {"warehouse": self.warehouse, "is_active": 1, "is_unassigned": 0}
		):
			frappe.throw(_("{0} has no locations to count yet.").format(self.warehouse))
		self.company = wh.company

	def on_trash(self):
		counts = frappe.get_all(
			"Location Inventory", filters={"inventory": self.name, "docstatus": ("<", 2)}, pluck="name"
		)
		if counts:
			frappe.throw(
				_("{0} already has counts ({1}). Complete it instead; an inventory that has "
				  "posted stock is part of the record.").format(self.name, ", ".join(counts[:5]))
			)

	# ------------------------------------------------------------------
	# lifecycle
	# ------------------------------------------------------------------
	def complete(self):
		if self.status != "Open":
			frappe.throw(_("{0} is not open.").format(self.name))
		drafts = frappe.get_all(
			"Location Inventory",
			filters={"inventory": self.name, "docstatus": 0},
			fields=["name", "location_code"],
		)
		if drafts:
			frappe.throw(
				_("Still being counted: {0}. Post or discard those counts before completing the "
				  "inventory, or they would be left belonging to nothing.").format(
					", ".join("%s (%s)" % (d.location_code, d.name) for d in drafts)
				),
				title=_("Counts In Progress"),
			)
		self.update(progress_counters(self.name))
		self.status = "Completed"
		self.completed_on = now_datetime()
		self.completed_by = frappe.session.user
		self.flags.ignore_permissions = True
		self.save(ignore_permissions=True)
		log_activity(
			"Movement", "Completed inventory", self.name, warehouse=self.warehouse,
			reference_type="Warehouse Inventory",
			message=_("{0} of {1} locations counted").format(self.locations_done, self.locations_total),
		)

	def reopen(self):
		if self.status != "Completed":
			frappe.throw(_("{0} is not completed.").format(self.name))
		self.status = "Open"
		self.completed_on = None
		self.completed_by = None
		self.flags.ignore_permissions = True
		self.save(ignore_permissions=True)  # validate refuses if another is open by now

	def refresh_progress(self):
		self.db_set(progress_counters(self.name), update_modified=False)


def progress_counters(inventory):
	p = progress(inventory)
	return {
		"locations_total": p["total"],
		"locations_done": p["done"],
		"locations_in_progress": p["in_progress"],
		"difference_lines": p["difference_lines"],
	}


def progress(inventory, with_locations=False):
	"""Every location of the warehouse, and where it stands in this inventory.

	done      a posted count belongs to this inventory
	progress  a draft count does
	waiting   neither does — including a location whose count here was cancelled
	"""
	doc = frappe.db.get_value("Warehouse Inventory", inventory, ["name", "warehouse"], as_dict=True)
	if not doc:
		frappe.throw(_("Inventory {0} does not exist.").format(inventory))

	fields = ["name", "location_code", "location_name", "zone"]
	locs = frappe.get_all(
		"Warehouse Location",
		filters={"warehouse": doc.warehouse, "is_active": 1, "is_unassigned": 0},
		fields=fields,
		limit_page_length=0,
	)
	counts = frappe.get_all(
		"Location Inventory",
		filters={"inventory": inventory, "docstatus": ("<", 2)},
		fields=["name", "location", "docstatus", "counted_lines", "difference_lines", "net_difference",
		        "counted_by", "posting_date", "stock_reconciliation", "modified"],
		order_by="docstatus desc, modified desc",
		limit_page_length=0,
	)
	by_location = {}
	for c in counts:
		by_location.setdefault(c.location, c)  # a posted count wins over a draft

	# a location counted here and deactivated since is still part of this stocktake
	known = {l.name for l in locs}
	missing = [loc for loc in by_location if loc not in known]
	if missing:
		locs += frappe.get_all("Warehouse Location", filters={"name": ("in", missing)}, fields=fields)

	held = {}
	zones = {}
	if with_locations:
		held = {
			r.location: r
			for r in frappe.db.sql(
				"""select location, count(*) as items, sum(qty) as qty from `tabLocation Stock`
				   where warehouse = %s and qty > 0 group by location""",
				(doc.warehouse,),
				as_dict=True,
			)
		}
		zones = {
			z.name: z
			for z in frappe.get_all(
				"Warehouse Zone", filters={"warehouse": doc.warehouse},
				fields=["name", "zone_code", "zone_name"], limit_page_length=0,
			)
		}

	done = in_progress = differences = 0
	rows = []
	for l in sorted(locs, key=lambda x: natural_key(x.location_code)):
		c = by_location.get(l.name)
		state = "done" if c and c.docstatus == 1 else ("progress" if c else "waiting")
		if state == "done":
			done += 1
			differences += cint(c.difference_lines)
		elif state == "progress":
			in_progress += 1
		if with_locations:
			h = held.get(l.name) or {}
			z = zones.get(l.zone) or {}
			rows.append(
				{
					"location": l.name,
					"location_code": l.location_code,
					"location_name": l.location_name,
					"zone": l.zone or "",
					"zone_label": z.get("zone_name") or z.get("zone_code") or "",
					"items": cint(h.get("items")),
					"qty": flt(h.get("qty")),
					"state": state,
					"count": c.name if c else None,
					"counted_by": c.counted_by if c else None,
					"posted_on": c.posting_date if state == "done" else None,
					"counted_lines": cint(c.counted_lines) if c else 0,
					"difference_lines": cint(c.difference_lines) if c else 0,
					"net_difference": flt(c.net_difference) if c else 0,
					"stock_reconciliation": c.stock_reconciliation if c else None,
				}
			)
	return {
		"total": len(locs),
		"done": done,
		"in_progress": in_progress,
		"waiting": len(locs) - done - in_progress,
		"difference_lines": differences,
		"locations": rows,
	}
