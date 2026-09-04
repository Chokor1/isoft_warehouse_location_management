# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt
#
# Bridges the documents that bring goods in -> Isoft Location Manager location stock.
#
# Purchase Receipt, and Purchase Invoice when it updates stock. This is the put-away
# side, and it is deliberately optional: a line with no location simply lands in
# unassigned stock, which is a true statement about where the goods are rather than a
# missing one. Nothing here can refuse a purchase.
#
# A *return* sends goods back to the supplier, which takes stock out — so it resolves and
# is held to the same rule as any other outbound move.

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

LOCATION_FIELD = "custom_to_location"


def _row_qty(row):
	"""Quantity in stock UOM — the unit location balances are kept in."""
	return flt(row.get("stock_qty")) or flt(row.get("qty"))


def _moves_stock(doc):
	if doc.doctype == "Purchase Receipt":
		return True
	return bool(doc.get("update_stock"))


def _returning(doc):
	return bool(doc.get("is_return"))


def validate(doc, method=None):
	if not is_enabled("purchase") or not _moves_stock(doc):
		return

	# When arriving stock may not be placed, any location on the row is cleared rather
	# than refused: the receiver did nothing wrong, the warehouse simply distributes
	# later. The goods land in unassigned stock, which is exactly where they are.
	if not setting("allow_location_on_in"):
		for row in doc.items:
			if row.get(LOCATION_FIELD):
				row.set(LOCATION_FIELD, None)

	for row in doc.items:
		location = row.get(LOCATION_FIELD)
		if not location:
			continue
		if not row.warehouse:
			frappe.throw(_("Row #{0}: a location needs a warehouse.").format(row.idx))
		if not is_warehouse_enabled(row.warehouse):
			frappe.throw(
				_("Row #{0}: warehouse {1} is not enabled for Isoft Location Manager.").format(
					row.idx, row.warehouse
				)
			)
		loc_wh = frappe.db.get_value("Warehouse Location", location, "warehouse")
		if loc_wh != row.warehouse:
			frappe.throw(
				_("Row #{0}: location {1} belongs to {2}, not {3}.").format(
					row.idx, location, loc_wh, row.warehouse
				)
			)

	if _returning(doc):
		resolve_returns(doc)


def before_submit(doc, method=None):
	"""Nothing to settle on the way in.

	A put-away location is a decision somebody makes standing at the shelf, so it is
	never guessed at: the field stays empty until it is chosen. A line left blank is not
	a missing answer — the goods are in the warehouse and not yet on a location, which is
	exactly what unassigned stock means.

	A *return* is the other direction: goods leaving again, settled like any outbound line.
	"""
	if not is_enabled("purchase") or not _moves_stock(doc):
		return
	if _returning(doc):
		resolve_returns(doc)


def resolve_returns(doc):
	"""A return takes stock out, so it is allocated and checked like any outbound line."""
	from isoft_warehouse_location_management.isoft_location_manager.location_resolver import auto_resolve_enabled

	if not auto_resolve_enabled():
		return
	claimed = {}
	for row in doc.items:
		qty = abs(_row_qty(row))
		if not row.warehouse or qty <= 0 or not is_warehouse_enabled(row.warehouse):
			continue
		if alloc.is_settled(row, row.warehouse, "out"):
			continue
		rows, short = alloc.top_up(
			row.warehouse, row.item_code, qty, row.get("custom_from_location"), "out"
		)
		rows = _take_claimed(rows, claimed, row.warehouse, row.item_code, qty)
		if rows:
			alloc.write_row(row, rows)
		if short > 0.001:
			frappe.msgprint(
				_("Row #{0}: {1} of {2} is not on any location in {3}.").format(
					row.idx, flt(short), row.item_code, row.warehouse
				),
				indicator="orange", alert=True,
			)
	for row in doc.items:
		if doc.docstatus == 1:
			alloc.require_settled(row, row.warehouse, row.idx, "out")


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
	if not is_enabled("purchase") or not _moves_stock(doc):
		return

	unassigned = unassigned_location_names()
	by_wh = {}
	returning = _returning(doc)

	for row in doc.items:
		qty = abs(_row_qty(row))
		if qty <= 0 or not row.warehouse or not is_warehouse_enabled(row.warehouse):
			continue

		if returning:
			for pick in alloc.read_row(row):
				if pick["location"] in unassigned or flt(pick["qty"]) <= 0:
					continue
				by_wh.setdefault(row.warehouse, []).append(
					{"item_code": row.item_code, "qty": flt(pick["qty"]),
					 "source_location": pick["location"]}
				)
			continue

		location = row.get(LOCATION_FIELD)
		# a line that lands in unassigned stock is not a movement: unassigned is the
		# remainder, so leaving it alone is already the right answer
		if not location or location in unassigned:
			continue
		by_wh.setdefault(row.warehouse, []).append(
			{"item_code": row.item_code, "qty": qty, "target_location": location}
		)

	for warehouse, items in by_wh.items():
		_make_movement(doc, "Stock Out" if returning else "Stock In", warehouse, items)


def _make_movement(doc, entry_type, warehouse, items):
	mv = frappe.get_doc(
		{
			"doctype": "Location Stock Movement",
			"entry_type": entry_type,
			"warehouse": warehouse,
			"posting_date": doc.posting_date,
			"reference_doctype": doc.doctype,
			"reference_sales_document": doc.name,
			"remarks": _("Auto-created from {0} {1}").format(_(doc.doctype), doc.name),
			"items": items,
		}
	)
	mv.flags.ignore_permissions = True
	mv.insert(ignore_permissions=True)
	mv.submit()


def on_cancel(doc, method=None):
	# Never gated: movements that exist must be reversed even if the module was switched
	# off in the meantime, or the ledger keeps holding stock that has gone.
	for name in frappe.get_all(
		"Location Stock Movement",
		filters={"reference_sales_document": doc.name, "reference_doctype": doc.doctype, "docstatus": 1},
		pluck="name",
	):
		mv = frappe.get_doc("Location Stock Movement", name)
		mv.flags.ignore_permissions = True
		mv.cancel()
