# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt
#
# One item row, several shelves.
#
# When a line's quantity is spread across more than one location, the row is NOT split.
# Splitting it would change the shape of the document itself, and a Sales Invoice or
# Delivery Note line is a fiscal record — SAFT-T, the AGT e-invoicing payload and every
# print format count and total those rows. Where the goods were picked from is warehouse
# detail; it must never alter what the document says it sold.
#
# So the split lives *inside* the row, as an allocation on the row's own field:
#
#     [{"location": "02-DEMO-A1", "qty": 60}, {"location": "02-DEMO-B1", "qty": 40}]
#
# `custom_from_location` keeps the largest location, so anything that reads a single value
# still gets a sensible one. The location ledger reads the allocation and moves each
# shelf separately — a Location Stock Movement may have as many lines as it likes,
# because it is internal.

import json

import frappe
from frappe import _
from frappe.utils import flt

from isoft_warehouse_location_management.isoft_location_manager.doctype.location_stock.location_stock import (
	get_balance,
	unassigned_qty,
)

ALLOCATION_FIELD = "custom_location_allocation"
TOL = 1e-6


# ======================================================================
# reading and writing
# ======================================================================
def parse(value):
	"""Read an allocation off a row. Always returns a list, never raises."""
	if not value:
		return []
	if isinstance(value, (list, tuple)):
		rows = value
	else:
		try:
			rows = json.loads(value)
		except (ValueError, TypeError):
			return []
	out = []
	for r in rows or []:
		location = (r or {}).get("location")
		qty = flt((r or {}).get("qty"))
		if location and qty > TOL:
			out.append({"location": location, "qty": qty})
	return out


def dump(rows):
	"""Serialise an allocation.

	Every settled row carries one, even when the whole line came off a single location:
	the field is the record of where the goods left from, and a record that is only
	written some of the time is not one anybody can read. It is also what the location
	movement is built from, so the two always agree.
	"""
	rows = [r for r in (rows or []) if r.get("location") and flt(r.get("qty")) > TOL]
	if not rows:
		return None
	return json.dumps(
		[{"location": r["location"], "qty": flt(r["qty"])} for r in rows], separators=(",", ":")
	)


def total(rows):
	return sum(flt(r.get("qty")) for r in (rows or []))


def primary(rows):
	"""The location a single-value reader should see: the one holding the most."""
	rows = sorted(rows or [], key=lambda r: -flt(r.get("qty")))
	return rows[0]["location"] if rows else None


def row_qty(row):
	"""A row's quantity in stock UOM, whichever document it belongs to."""
	return (
		flt(row.get("stock_qty"))
		or flt(row.get("transfer_qty"))
		or flt(row.get("qty"))
	)


def is_settled(row, warehouse=None, direction="out"):
	"""Does this row already carry an allocation worth keeping?

	An allocation is a leftover, not a decision, when it no longer describes the line —
	either because the quantity was edited after it was settled, or because the goods
	have since moved off the location it names. Both happen quietly, and both would
	otherwise surface far downstream: the first as a validation message about numbers
	nobody typed, the second as the ledger refusing to go negative at submit, naming a
	location the operator cannot even see. Re-settling is the honest answer to both.
	"""
	rows = parse(row.get(ALLOCATION_FIELD))
	if not rows:
		return False
	if abs(total(rows) - abs(row_qty(row))) > 0.001:
		return False
	if not warehouse or direction != "out":
		return True

	from isoft_warehouse_location_management.isoft_location_manager.doctype.location_stock.location_stock import (
		get_balance,
		unassigned_qty,
	)

	for r in rows:
		meta = frappe.db.get_value(
			"Warehouse Location", r["location"], ["warehouse", "is_active", "is_unassigned"], as_dict=True
		)
		if not meta or not meta.is_active or meta.warehouse != warehouse:
			return False
		available = (
			unassigned_qty(warehouse, row.get("item_code"))
			if meta.is_unassigned
			else get_balance(r["location"], row.get("item_code"))
		)
		if flt(r["qty"]) > flt(available) + 0.001:
			return False
	return True


def read_row(row):
	"""The row's picks, whether it carries an allocation or just one location."""
	rows = parse(row.get(ALLOCATION_FIELD))
	if rows:
		return rows
	location = row.get("custom_from_location")
	qty = row_qty(row)
	return [{"location": location, "qty": abs(qty)}] if location and qty else []


def write_row(row, rows, persist=False):
	"""Put an allocation onto a row, keeping `custom_from_location` in step."""
	rows = [r for r in (rows or []) if r.get("location") and flt(r.get("qty")) > TOL]
	value = dump(rows)
	row.set(ALLOCATION_FIELD, value)
	row.set("custom_from_location", primary(rows))
	if persist and row.name:
		frappe.db.set_value(
			row.doctype,
			row.name,
			{ALLOCATION_FIELD: value, "custom_from_location": primary(rows)},
			update_modified=False,
		)
	return rows


# ======================================================================
# building an allocation
# ======================================================================
def top_up(warehouse, item_code, qty, preferred=None, direction="out"):
	"""Spread a quantity, starting from the location someone chose.

	A chosen location is where picking *starts*, not the only place it can come from.
	If the line needs more than that shelf holds, the rest spills into the remaining
	candidates in resolver order. Anything else means a cashier ringing up more than one
	shelf happens to hold cannot complete the sale — which is not the cashier's problem
	to solve at the till.

	Returns (rows, shortfall). One row back means the preferred location covered it.
	"""
	from isoft_warehouse_location_management.isoft_location_manager.location_resolver import resolve_one

	qty = abs(flt(qty))
	if qty <= TOL:
		return [], 0.0

	res = resolve_one(warehouse, item_code, direction, qty) or {}
	candidates = list(res.get("candidates") or [])
	if not candidates:
		return [], qty

	# The chosen location goes first, whatever the resolver would have ranked — but only
	# if it actually holds the item. A preference that holds none of it is not a decision
	# worth honouring: it is almost always a value left behind on the row (copied in with
	# a duplicated line, or true until the stock moved), and the field is internal, so
	# nobody can see it to correct it. Honouring it would refuse the document over a
	# location the operator never chose, while a location with the goods sits next to it.
	if preferred:
		chosen = next((c for c in candidates if c["location"] == preferred), None)
		if chosen:
			candidates.remove(chosen)
			candidates.insert(0, chosen)

	rows, left = [], qty
	for c in candidates:
		if left <= TOL:
			break
		take = min(left, flt(c.get("qty")))
		if take <= TOL:
			continue
		rows.append({"location": c["location"], "qty": take})
		left -= take
	return rows, max(left, 0.0)


def allocate(warehouse, item_code, qty, direction="out"):
	"""Spread a quantity across the locations that can supply it.

	Returns (rows, shortfall). A shortfall means the locations between them cannot
	cover the line — the caller decides whether that is a warning or a refusal.
	"""
	from isoft_warehouse_location_management.isoft_location_manager.location_resolver import resolve_one

	qty = abs(flt(qty))
	if qty <= TOL:
		return [], 0.0

	res = resolve_one(warehouse, item_code, direction, qty) or {}
	if not res.get("candidates"):
		return [], qty

	rows, left = [], qty
	for c in res["candidates"]:
		if left <= TOL:
			break
		take = min(left, flt(c.get("qty")))
		if take <= TOL:
			continue
		rows.append({"location": c["location"], "qty": take})
		left -= take
	return rows, max(left, 0.0)


# ======================================================================
# validation
# ======================================================================
def require_settled(row, warehouse, idx=None, direction="out"):
	"""Stock going out has to say where it came from.

	Stock coming *in* is different: a line nobody put away is simply unassigned stock,
	which is a true and useful answer. But stock leaving a location the ledger cannot
	name is stock the ledger has lost track of, so that is refused.
	"""
	from isoft_warehouse_location_management.isoft_location_manager.api import is_warehouse_enabled, setting

	if direction != "out" or not setting("require_location_on_out"):
		return
	if not warehouse or not is_warehouse_enabled(warehouse):
		return
	qty = abs(row_qty(row))
	if qty <= TOL:
		return

	rows = parse(row.get(ALLOCATION_FIELD)) or read_row(row)
	short = qty - total(rows)
	if short > 0.001:
		frappe.throw(
			_("Row #{0}: {1} of {2} has no location to come out of in {3}. "
			  "Put it away first, or allow picking from unassigned stock in Picking Settings.").format(
				idx or row.get("idx"), flt(short), row.get("item_code"), warehouse
			)
		)


def validate_row(row, warehouse, idx=None, strict=True):
	"""An allocation has to add up to the line, and each shelf has to have the goods."""
	rows = parse(row.get(ALLOCATION_FIELD))
	if not rows:
		return

	idx = idx or row.get("idx")
	qty = abs(row_qty(row))
	if abs(total(rows) - qty) > 0.001:
		frappe.throw(
			_("Row #{0}: the locations add up to {1} but the line is for {2}.").format(
				idx, total(rows), qty
			)
		)

	seen = set()
	for r in rows:
		location = r["location"]
		if location in seen:
			frappe.throw(_("Row #{0}: location {1} is listed twice.").format(idx, location))
		seen.add(location)

		meta = frappe.db.get_value(
			"Warehouse Location", location, ["warehouse", "is_active", "is_unassigned"], as_dict=True
		)
		if not meta:
			frappe.throw(_("Row #{0}: location {1} does not exist.").format(idx, location))
		if meta.warehouse != warehouse:
			frappe.throw(
				_("Row #{0}: location {1} belongs to {2}, not {3}.").format(
					idx, location, meta.warehouse, warehouse
				)
			)
		if not meta.is_active:
			frappe.throw(_("Row #{0}: location {1} is inactive.").format(idx, location))

		if not strict:
			continue
		available = (
			unassigned_qty(warehouse, row.item_code)
			if meta.is_unassigned
			else get_balance(location, row.item_code)
		)
		if flt(r["qty"]) > available + 0.001:
			frappe.throw(
				_("Row #{0}: {1} taken from {2}, which holds {3}.").format(
					idx, flt(r["qty"]), location, flt(available)
				)
			)


# ======================================================================
# what the UI needs
# ======================================================================
@frappe.whitelist()
def suggest(warehouse, item_code, qty, direction="out", preferred=None):
	"""Propose an allocation for a line — what the dialog opens with.

	`preferred` is where the operator said to start, and it is honoured only while that
	location actually holds something: a stale choice, or one left behind from another
	warehouse, must not put quantity on a location that has none.
	"""
	from isoft_warehouse_location_management.isoft_location_manager.api import is_enabled

	if not is_enabled():
		return {"rows": [], "shortfall": 0, "candidates": []}

	from isoft_warehouse_location_management.isoft_location_manager.location_resolver import resolve_one

	res = resolve_one(warehouse, item_code, direction, qty) or {}
	rows, shortfall = top_up(warehouse, item_code, qty, preferred, direction)
	return {
		"rows": rows,
		"shortfall": shortfall,
		"candidates": res.get("candidates") or [],
		"mode": res.get("mode"),
		"reason": res.get("reason"),
	}


@frappe.whitelist()
def describe(value):
	"""A one-line summary for the grid: `A-01 60 + B-01 40`."""
	rows = parse(value)
	if not rows:
		return ""
	return "  +  ".join("{0} {1}".format(r["location"], flt(r["qty"])) for r in rows)
