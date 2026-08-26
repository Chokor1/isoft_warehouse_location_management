# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt
#
# The location ledger partitions a warehouse's real stock across its locations.
#
#     Bin.actual_qty  ==  sum(Location Stock rows)  +  unassigned remainder
#
# Only *real* locations get a Location Stock row. The Unassigned Stock location is the
# remainder, computed on read — so it is never wrong, never needs seeding, and
# absorbs every stock movement the app does not otherwise track.

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from isoft_warehouse_location_management.isoft_location_manager.doctype.warehouse_location.warehouse_location import (
	get_unassigned_location,
	is_unassigned,
)


class LocationStock(Document):
	pass


def get_balance(location, item_code):
	"""Current digital qty of an item in a location (0 if no row yet)."""
	if not location or not item_code:
		return 0.0
	if is_unassigned(location):
		warehouse = frappe.db.get_value("Warehouse Location", location, "warehouse")
		return unassigned_qty(warehouse, item_code)
	return flt(
		frappe.db.get_value("Location Stock", {"location": location, "item_code": item_code}, "qty")
	)


def assigned_qty(warehouse, item_code):
	"""Total of an item held across the warehouse's real (non-unassigned) locations."""
	return flt(
		frappe.db.get_value(
			"Location Stock", {"warehouse": warehouse, "item_code": item_code}, "sum(qty)"
		)
	)


def bin_qty(warehouse, item_code):
	return flt(frappe.db.get_value("Bin", {"warehouse": warehouse, "item_code": item_code}, "actual_qty"))


def unassigned_qty(warehouse, item_code):
	"""Stock in the warehouse that has not been put away into a location.

	May come out negative when stock left the warehouse through a document the app
	does not mirror (a Delivery Note, a POS sale) while the location balances still
	claim it. Callers that offer stock to pick should use `max(0, ...)`; the
	reconciliation view deliberately shows the raw number.
	"""
	if not warehouse or not item_code:
		return 0.0
	return bin_qty(warehouse, item_code) - assigned_qty(warehouse, item_code)


def bin_quantities(warehouse, item_codes):
	"""{item_code: actual_qty} in one query, for resolving a whole document at once."""
	out = {}
	if not warehouse or not item_codes:
		return out
	rows = frappe.get_all(
		"Bin",
		filters={"warehouse": warehouse, "item_code": ["in", list(item_codes)]},
		fields=["item_code", "actual_qty"],
		limit_page_length=0,
	)
	for r in rows:
		out[r.item_code] = flt(r.actual_qty)
	return out


def location_balances(warehouse, item_codes):
	"""{item_code: {location: qty}} for the real locations of one warehouse."""
	out = {}
	if not warehouse or not item_codes:
		return out
	rows = frappe.get_all(
		"Location Stock",
		filters={"warehouse": warehouse, "item_code": ["in", list(item_codes)]},
		fields=["item_code", "location", "qty"],
		limit_page_length=0,
	)
	for r in rows:
		out.setdefault(r.item_code, {})[r.location] = flt(r.qty)
	return out


def apply_delta(warehouse, location, item_code, delta):
	"""Add `delta` (may be negative) to a location balance.

	Unassigned locations are skipped: their quantity is derived, so moving stock in or
	out of one is recorded entirely by the real location on the other side.
	Never posts any GL entry or Stock Ledger Entry.
	"""
	delta = flt(delta)
	if not delta or not location:
		return
	if is_unassigned(location):
		return

	# `for_update` locks the row for the rest of the transaction, so the read-add-write
	# below cannot interleave with another submit touching the same balance.
	name = frappe.db.get_value(
		"Location Stock", {"location": location, "item_code": item_code}, "name", for_update=True
	)

	if not name:
		name = _create_balance_row(warehouse, location, item_code)
		if not name:  # lost the race — another submit just created it
			name = frappe.db.get_value(
				"Location Stock", {"location": location, "item_code": item_code}, "name", for_update=True
			)

	# Single atomic statement: two concurrent submits cannot lose a delta.
	frappe.db.sql(
		"""update `tabLocation Stock`
		set qty = qty + %s, modified = %s, modified_by = %s
		where name = %s""",
		(delta, frappe.utils.now(), frappe.session.user, name),
	)

	new_qty = flt(frappe.db.get_value("Location Stock", name, "qty"))
	if new_qty < -1e-9:
		frappe.throw(
			_("Location {0} holds only {1} of {2} — cannot take out {3}.").format(
				location, flt(new_qty - delta), item_code, abs(delta)
			)
		)


def _create_balance_row(warehouse, location, item_code):
	"""Insert a zero balance row. Returns None if a concurrent insert won the race."""
	doc = frappe.get_doc(
		{
			"doctype": "Location Stock",
			"warehouse": warehouse,
			"location": location,
			"item_code": item_code,
			"qty": 0,
		}
	)
	doc.flags.ignore_permissions = True
	try:
		doc.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		return None
	return doc.name


