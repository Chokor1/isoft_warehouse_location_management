# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt
#
# The Picking Sheet: the piece of paper somebody carries into the warehouse.
#
# It answers one question per line — *what to fetch, how much, and from which location* —
# and nothing else. No prices, no customer terms, no tax: the person walking the racks
# does not need them, and a document full of things they must ignore is a document they
# will stop reading.
#
# It is built from the same allocation the ledger is built from, so the sheet and the
# stock movement can never disagree.

import frappe
from frappe import _
from frappe.utils import flt

from isoft_warehouse_location_management.isoft_location_manager import location_allocation as alloc
from isoft_warehouse_location_management.isoft_location_manager.api import is_enabled, is_warehouse_enabled

SOURCE_FIELDS = ("s_warehouse", "warehouse")


def _source_warehouse(row):
	for f in SOURCE_FIELDS:
		if row.get(f):
			return row.get(f)
	return None


def is_relevant(doc):
	"""Is there anything to pick here?

	A Stock Entry only qualifies when it actually takes stock out of a warehouse this
	app runs in — a pure receipt has nothing to fetch.
	"""
	if not is_enabled():
		return False
	if doc.doctype == "Sales Invoice" and not doc.get("update_stock"):
		return False
	if doc.get("is_return"):
		return False
	return any(
		is_warehouse_enabled(_source_warehouse(row))
		for row in (doc.get("items") or [])
		if _source_warehouse(row)
	)


def picking_lines(doc):
	"""One entry per document line, carrying where each part of it comes from.

	The document line is never split — that stays true on paper as well. A line picked
	off three locations is still one line, with three places named under it.
	"""
	lines = []
	for row in doc.get("items") or []:
		warehouse = _source_warehouse(row)
		if not warehouse or not is_warehouse_enabled(warehouse):
			continue
		qty = abs(flt(row.get("stock_qty")) or flt(row.get("transfer_qty")) or flt(row.get("qty")))
		if qty <= 0:
			continue

		picks = []
		for p in alloc.read_row(row):
			if flt(p["qty"]) <= 0:
				continue
			meta = frappe.db.get_value(
				"Warehouse Location", p["location"],
				["location_name", "is_unassigned", "zone"], as_dict=True
			) or frappe._dict()
			zone = frappe.db.get_value("Warehouse Zone", meta.zone, "zone_name") if meta.zone else None
			picks.append({
				"location": _("Not put away") if meta.is_unassigned else p["location"],
				"location_name": None if meta.is_unassigned else meta.location_name,
				"zone": zone,
				"qty": flt(p["qty"]),
				"is_unassigned": bool(meta.is_unassigned),
			})

		lines.append({
			"idx": row.get("idx"),
			"item_code": row.get("item_code"),
			"item_name": row.get("item_name"),
			"qty": qty,
			"uom": row.get("stock_uom") or row.get("uom"),
			"warehouse": warehouse,
			"picks": picks,
			# a line nobody has settled yet still belongs on the sheet — the picker needs
			# to know it exists, and that nobody has said where it comes from
			"unplaced": max(qty - sum(flt(p["qty"]) for p in picks), 0),
		})
	return lines


def sheet_header(doc):
	"""Everything the top of the sheet needs, in one lookup."""
	company = doc.get("company")
	warehouses = sorted({
		_source_warehouse(r) for r in (doc.get("items") or [])
		if _source_warehouse(r) and is_warehouse_enabled(_source_warehouse(r))
	})
	return {
		"logo": frappe.db.get_value("Company", company, "company_logo") if company else None,
		"company": company,
		"warehouses": warehouses,
		"total_qty": sum(flt(l["qty"]) for l in picking_lines(doc)),
	}


@frappe.whitelist()
def is_available(doctype, name):
	"""Asked by the form before it offers the button."""
	if not frappe.has_permission(doctype, "read", doc=name):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	doc = frappe.get_doc(doctype, name)
	return {"available": bool(is_relevant(doc)), "format": FORMAT_FOR.get(doctype)}


FORMAT_FOR = {
	"Delivery Note": "Picking Sheet - Delivery Note",
	"Sales Invoice": "Picking Sheet - Sales Invoice",
	"Stock Entry": "Picking Sheet - Stock Entry",
}
