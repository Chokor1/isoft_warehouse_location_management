# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt
#
# Bridges ERPNext Stock Entry -> Isoft Location Manager location stock.
# Each Stock Entry item row can carry a source/target location (custom fields).
# Rows leaving a warehouse are resolved automatically, so a warehouse where an item
# lives in exactly one location never needs anyone to pick it. Rows arriving are not:
# a put-away location is chosen by hand, and a blank one means unassigned stock.
# On submit the picks are mirrored into Location Stock Movements (cost-free, no GL /
# no Stock Ledger Entry); on cancel they are reversed.

import frappe
from frappe import _
from frappe.utils import flt

from isoft_warehouse_location_management.isoft_location_manager import location_allocation as alloc
from isoft_warehouse_location_management.isoft_location_manager.api import (
	is_enabled,
	is_warehouse_enabled,
	setting,
)
from isoft_warehouse_location_management.isoft_location_manager.doctype.warehouse_location.warehouse_location import (
	unassigned_location_names,
)


def _row_qty(row):
	return flt(row.get("transfer_qty")) or flt(row.get("qty"))


def validate(doc, method=None):
	"""Guard the location picks: location must belong to the row warehouse, which must be enabled.

	Locations are settled here as well as at submit, so a saved draft already records
	where each line will be taken from.
	"""
	if not is_enabled("stock_entry"):
		return

	# arriving stock may be barred from going straight onto a location
	if not setting("allow_location_on_in"):
		for row in doc.items:
			if row.get("custom_to_location"):
				row.set("custom_to_location", None)

	# order matters: clean the row, settle it, then check what was settled
	for row in doc.items:
		if row.get("custom_from_location") and not row.get(alloc.ALLOCATION_FIELD):
			_check(row.custom_from_location, row.s_warehouse, row.idx, "From",
				row=row, field="custom_from_location")

	before_submit(doc)

	for row in doc.items:
		if row.get(alloc.ALLOCATION_FIELD):
			alloc.validate_row(row, row.s_warehouse, row.idx, strict=False)
			alloc.sync_primary(row)
		# only the source side is mandatory: a target left blank is unassigned stock,
		# which is a true answer rather than a missing one
		# a draft may be unfinished; what leaves the building may not
		if row.get("s_warehouse") and doc.docstatus == 1:
			alloc.require_settled(row, row.s_warehouse, row.idx, "out")
		if row.get("custom_to_location"):
			_check(row.custom_to_location, row.t_warehouse, row.idx, "To")


def _check(location, warehouse, idx, side, row=None, field=None):
	"""Returns True when the value is sound; clears it and returns False when it is not.

	The From Location is internal — hidden, filled by the resolver — so a value that no
	longer fits the row is cleared rather than thrown at the operator, who has no way to
	see or correct it. The To Location is a real, visible choice, so that one is refused.
	"""
	heal = row is not None and field is not None

	def bad(msg):
		if heal:
			row.set(field, None)
			return False
		frappe.throw(msg)

	if not warehouse:
		return bad(_("Row #{0}: {1} Location needs a {1} Warehouse.").format(idx, side))
	if not is_warehouse_enabled(warehouse):
		return bad(
			_("Row #{0}: warehouse {1} is not enabled for Isoft Location Manager, so a location cannot be set.").format(idx, warehouse)
		)
	sec_wh = frappe.db.get_value("Warehouse Location", location, "warehouse")
	if sec_wh != warehouse:
		return bad(_("Row #{0}: location {1} does not belong to warehouse {2}.").format(idx, location, warehouse))
	return True


def before_submit(doc, method=None):
	"""Fill in the locations nobody chose.

	Only unambiguous answers are written: one location holding the item on the way out,
	or the item's known home on the way in. Anything genuinely ambiguous is left blank
	and simply stays in unassigned stock.
	"""
	if not is_enabled("stock_entry"):
		return

	from isoft_warehouse_location_management.isoft_location_manager.location_resolver import auto_resolve_enabled

	if not auto_resolve_enabled():
		return

	# Taking stock out can span several shelves, so it gets an allocation on the row
	# rather than extra rows. Putting stock away lands in one place.
	claimed = {}
	for row in doc.items:
		warehouse = row.get("s_warehouse")
		qty = _row_qty(row)
		# a settled row already says everything — but only while it still adds up
		if alloc.is_settled(row, warehouse, "out"):
			continue
		if not warehouse or qty <= 0 or not is_warehouse_enabled(warehouse):
			continue
		# several locations could supply it and none is declared: that is a decision
		if alloc.needs_a_choice(warehouse, row.item_code, qty):
			continue
		# a chosen location is where picking starts, not the only place it can come from
		rows, short = alloc.top_up(warehouse, row.item_code, qty, row.get("custom_from_location"), "out")
		rows = _take_claimed(rows, claimed, warehouse, row.item_code, qty)
		if short > 0.001:
			frappe.msgprint(
				_("Row #{0}: {1} of {2} is not on any location in {3}.").format(
					row.idx, flt(short), row.item_code, warehouse
				),
				indicator="orange",
				alert=True,
			)
		if rows:
			alloc.write_row(row, rows)

	# Nothing is written on the way in. A put-away location is a decision somebody makes
	# standing at the shelf, so the field stays empty until it is chosen; a line left
	# blank means the goods are in the warehouse and not yet on a location, which is what
	# unassigned stock is. Only the outbound side above is settled automatically.


def _take_claimed(rows, claimed, warehouse, item_code, qty):
	"""Reduce an allocation by what earlier lines of this document already took."""
	out, left = [], qty
	for r in rows:
		key = (warehouse, item_code, r["location"])
		already = claimed.get(key, 0.0)
		take = min(left, max(flt(r["qty"]) - already, 0.0))
		if take <= 0:
			continue
		claimed[key] = already + take
		out.append({"location": r["location"], "qty": take})
		left -= take
		if left <= 0:
			break
	return out


def on_submit(doc, method=None):
	if not is_enabled("stock_entry"):
		return

	# group location deltas by warehouse & direction
	unassigned = unassigned_location_names()
	out_by_wh = {}   # s_warehouse -> [{item_code, qty, source_location}]
	in_by_wh = {}    # t_warehouse -> [{item_code, qty, target_location}]
	for row in doc.items:
		qty = _row_qty(row)
		if qty <= 0:
			continue
		# A pick that resolves to unassigned stock is not a movement: unassigned is the
		# remainder, so leaving it alone is already the right answer.
		# One entry line may come off several shelves; the movement carries the detail.
		if row.s_warehouse and is_warehouse_enabled(row.s_warehouse):
			for pick in alloc.read_row(row):
				if pick["location"] in unassigned or flt(pick["qty"]) <= 0:
					continue
				out_by_wh.setdefault(row.s_warehouse, []).append(
					{
						"item_code": row.item_code,
						"qty": flt(pick["qty"]),
						"source_location": pick["location"],
					}
				)
		if (
			row.get("custom_to_location")
			and row.custom_to_location not in unassigned
			and row.t_warehouse
			and is_warehouse_enabled(row.t_warehouse)
		):
			in_by_wh.setdefault(row.t_warehouse, []).append(
				{"item_code": row.item_code, "qty": qty, "target_location": row.custom_to_location}
			)

	for warehouse, items in out_by_wh.items():
		_make_movement(doc, "Stock Out", warehouse, items)
	for warehouse, items in in_by_wh.items():
		_make_movement(doc, "Stock In", warehouse, items)


def _make_movement(se, entry_type, warehouse, items):
	mv = frappe.get_doc(
		{
			"doctype": "Location Stock Movement",
			"entry_type": entry_type,
			"warehouse": warehouse,
			"posting_date": se.posting_date,
			"reference_stock_entry": se.name,
			"remarks": _("Auto-created from Stock Entry {0}").format(se.name),
			"items": items,
		}
	)
	mv.flags.ignore_permissions = True
	mv.insert(ignore_permissions=True)
	mv.submit()


def on_cancel(doc, method=None):
	# Never gated: movements that exist must be reversed even if the module was switched
	# off in the meantime, or the ledger is left holding stock that has gone.
	for name in frappe.get_all(
		"Location Stock Movement",
		filters={"reference_stock_entry": doc.name, "docstatus": 1},
		pluck="name",
	):
		mv = frappe.get_doc("Location Stock Movement", name)
		mv.flags.ignore_permissions = True
		mv.cancel()
