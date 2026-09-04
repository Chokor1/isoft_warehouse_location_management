# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt
#
# Bridges the documents that ship goods -> Isoft Location Manager location stock.
#
# A Delivery Note, a stock-updating Sales Invoice, or a POS sale all drain
# `Bin.actual_qty`. Without this the location balances would keep claiming stock that
# has already left the building, and the unassigned remainder would go negative.
#
# Each item row carries a location (custom field). Blank rows are resolved just before
# submit — a cashier is never asked which shelf a sale came off — and the pick is then
# mirrored into a cost-free Location Stock Movement. Returns run the other way.

import frappe
from frappe import _
from frappe.utils import flt

from isoft_warehouse_location_management.isoft_location_manager import location_allocation as alloc
from isoft_warehouse_location_management.isoft_location_manager.api import is_enabled, is_warehouse_enabled
from isoft_warehouse_location_management.isoft_location_manager.doctype.warehouse_location.warehouse_location import (
	unassigned_location_names,
)

LOCATION_FIELD = "custom_from_location"


def _feature_for(doc):
	"""POS sales are gated separately from ordinary shipping."""
	if doc.doctype == "Sales Invoice" and doc.get("is_pos"):
		return "pos"
	return "delivery_note"


def _moves_stock(doc):
	"""Does submitting this document actually move stock out of a warehouse?"""
	if doc.doctype == "Delivery Note":
		return True
	return bool(doc.get("update_stock"))


def _row_qty(row):
	"""Quantity in stock UOM — the unit location balances are kept in."""
	return flt(row.get("stock_qty")) or flt(row.get("qty"))


# ======================================================================
# validation
# ======================================================================
def _drop_stale_locations(doc):
	"""Clear an internal location that does not fit its row.

	`custom_from_location` is hidden — nobody can see it, so nobody can fix it. Refusing
	a document over a value the operator never chose (copied in with a duplicated row,
	or left behind when the warehouse changed) is a dead end. It is cleared here, before
	anything is resolved, so the resolver starts from a clean row rather than treating a
	location from another warehouse as a preference.
	"""
	for row in doc.items:
		location = row.get(LOCATION_FIELD)
		if not location:
			continue
		if not row.warehouse:
			row.set(LOCATION_FIELD, None)
			continue
		if frappe.db.get_value("Warehouse Location", location, "warehouse") != row.warehouse:
			row.set(LOCATION_FIELD, None)


def validate(doc, method=None):
	if not is_enabled(_feature_for(doc)) or not _moves_stock(doc):
		return

	# order matters: clean the row, settle it, then check what was settled
	_drop_stale_locations(doc)

	# Settled on save, not only on submit: the row is the record of where the goods left
	# from, and a record that only appears at submit cannot be checked, corrected or
	# reported on while the document is still a draft.
	resolve_row_locations(doc)

	# a return puts stock back, which is an inbound move and never mandatory
	direction = "in" if doc.get("is_return") else "out"
	for row in doc.items:
		if row.get(alloc.ALLOCATION_FIELD):
			# a split line has to add up to the line and come off locations that have it
			alloc.validate_row(row, row.warehouse, row.idx, strict=False)
			alloc.sync_primary(row)
		# Only when it is actually going out. A draft is allowed to be unfinished — that
		# is what a draft is — and a line left for somebody to choose has to be saveable
		# while they are choosing.
		if doc.docstatus == 1:
			alloc.require_settled(row, row.warehouse, row.idx, direction)


# ======================================================================
# resolution
# ======================================================================
def before_submit(doc, method=None):
	"""Settle where every line is picked from.

	This is what keeps a POS fast: the cashier scans and takes payment, and the
	location is decided by the same resolver the warehouse screens use.
	"""
	resolve_row_locations(doc)


def resolve_row_locations(doc, persist=False, check_stock=True):
	"""Settle every row's location, topping it up when one shelf cannot cover the line.

	A location someone chose is where picking *starts*, not the only place it can come
	from. Taking a whole line off one shelf because that is the only field the screen
	had would drive it negative and refuse the sale — so a line bigger than its shelf
	spills into the next locations in resolver order, and the row carries the split.

	`check_stock` decides whether an existing allocation is re-examined against what the
	locations actually hold. That question only makes sense while the goods are still
	there — see `on_submit`.

	`persist` writes the value straight to the child row. That is needed because some
	sites auto-submit invoices with `ignore_validate`, which skips `before_submit`
	entirely — by the time the document is mirrored it is already submitted, so the
	field can no longer be set through a normal save.

	A line whose quantity spans several shelves gets an allocation on the row. The row
	is never split: these are fiscal documents, and how many lines they have is not the
	warehouse's business.
	"""
	filled = []
	if not is_enabled(_feature_for(doc)) or not _moves_stock(doc):
		return filled

	from isoft_warehouse_location_management.isoft_location_manager.location_resolver import auto_resolve_enabled

	if not auto_resolve_enabled():
		return filled

	# A return puts stock back, and putting away is never guessed at — the goods land in
	# unassigned stock unless somebody says otherwise. Only outbound lines are settled.
	if doc.get("is_return"):
		return filled
	direction = "out"

	# Allocated one line at a time, and each allocation is subtracted from what the next
	# line may claim — two lines of the same item must not both promise the same shelf.
	claimed = {}
	for row in doc.items:
		# a settled row already says everything — but only while it still adds up
		if not row.warehouse:
			continue
		if alloc.is_settled(row, row.warehouse if check_stock else None, direction):
			continue
		qty = abs(_row_qty(row))
		if qty <= 0 or not is_warehouse_enabled(row.warehouse):
			continue

		# Several locations could supply this, none of them declared: that is a decision,
		# and guessing at it puts goods on the counter that came off a shelf nobody chose.
		if alloc.needs_a_choice(row.warehouse, row.item_code, qty):
			continue

		rows, short = alloc.top_up(
			row.warehouse, row.item_code, qty, row.get(LOCATION_FIELD), direction
		)
		rows = _take_claimed(rows, claimed, row.warehouse, row.item_code, qty)
		if not rows:
			continue
		if short > 0.001:
			frappe.msgprint(
				_("Row #{0}: {1} of {2} is not on any location here, so that much was left unrecorded.").format(
					row.idx, flt(short), row.item_code
				),
				indicator="orange",
				alert=True,
			)
		alloc.write_row(row, rows, persist=persist)
		filled.append(row)
	return filled


def _take_claimed(rows, claimed, warehouse, item_code, qty):
	"""Reduce an allocation by what earlier lines of this document already took."""
	out, left = [], qty
	for r in rows:
		key = (warehouse, item_code, r["location"])
		already = claimed.get(key, 0.0)
		free = max(flt(r["qty"]) - already, 0.0)
		take = min(left, free)
		if take <= 0:
			continue
		claimed[key] = already + take
		out.append({"location": r["location"], "qty": take})
		left -= take
		if left <= 0:
			break
	return out


# ======================================================================
# mirroring
# ======================================================================
def on_submit(doc, method=None):
	if not is_enabled(_feature_for(doc)) or not _moves_stock(doc):
		return

	# Catch anything `before_submit` never got to see (see resolve_row_locations).
	#
	# Without checking availability: by now erpnext has already taken the quantity out of
	# the Bin, while this app has not yet taken it off the locations, so for the length of
	# this hook the unassigned remainder reads negative and every location looks unable to
	# supply what it is about to supply. An allocation settled a moment ago is still the
	# right answer — there is nothing left to re-decide here.
	resolve_row_locations(doc, persist=True, check_stock=False)

	unassigned = unassigned_location_names()
	by_warehouse = {}
	for row in doc.items:
		if not row.warehouse or not is_warehouse_enabled(row.warehouse):
			continue

		# a credit note carries negative quantities and puts stock back on the shelf
		returning = _row_qty(row) < 0 or bool(doc.get("is_return"))
		key = (row.warehouse, "Stock In" if returning else "Stock Out")
		field = "target_location" if returning else "source_location"

		# One document line can become several movement lines. That is fine — the
		# movement is internal; the invoice keeps exactly the rows it was written with.
		for pick in alloc.read_row(row):
			# Unassigned is the derived remainder, so a sale from it is already
			# accounted for by the Bin movement — recording it would double-count.
			if pick["location"] in unassigned:
				continue
			qty = abs(flt(pick["qty"]))
			if qty <= 0:
				continue
			by_warehouse.setdefault(key, []).append(
				{"item_code": row.item_code, "qty": qty, field: pick["location"]}
			)

	for (warehouse, entry_type), items in by_warehouse.items():
		_make_movement(doc, entry_type, warehouse, items)


def _make_movement(doc, entry_type, warehouse, items):
	mv = frappe.get_doc(
		{
			"doctype": "Location Stock Movement",
			"entry_type": entry_type,
			"warehouse": warehouse,
			"posting_date": doc.get("posting_date") or frappe.utils.nowdate(),
			"reference_sales_document": doc.name,
			"reference_doctype": doc.doctype,
			"remarks": _("Auto-created from {0} {1}").format(_(doc.doctype), doc.name),
			"items": items,
		}
	)
	mv.flags.ignore_permissions = True
	# The sale has already happened. A location that cannot cover it is a reporting
	# problem, not a reason to fail the shipment — warn and let it through.
	mv.flags.picking_validation_mode = "Warn"
	mv.insert(ignore_permissions=True)
	mv.submit()


def on_cancel(doc, method=None):
	# Never gated: a movement that exists must be reversed even if the module was
	# switched off in the meantime.
	for name in frappe.get_all(
		"Location Stock Movement",
		filters={"reference_sales_document": doc.name, "docstatus": 1},
		pluck="name",
	):
		mv = frappe.get_doc("Location Stock Movement", name)
		mv.flags.ignore_permissions = True
		mv.cancel()
