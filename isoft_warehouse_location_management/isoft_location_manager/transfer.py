# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt
#
# Getting a warehouse into the app, and back out of it.
#
# Three things can be imported, in the order a warehouse is actually described: the zones
# it is divided into, the locations inside them, and what sits on each location. Each is
# a flat sheet with named columns, so a row that fails says which row and why rather than
# failing the file.
#
# Nothing is applied until it has all been checked. A half-imported warehouse is worse
# than an unimported one: you cannot tell what happened without reading every row, and
# re-running the file would double the quantities.

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

KINDS = ("zones", "locations", "stock")

COLUMNS = {
	"zones": ["warehouse", "zone_code", "zone_name", "sequence", "description"],
	"locations": [
		"warehouse", "location_code", "location_name", "zone", "location_type",
		"max_qty", "barcode", "description",
	],
	"stock": ["warehouse", "location_code", "item_code", "qty"],
}

REQUIRED = {
	"zones": ["warehouse", "zone_code"],
	"locations": ["warehouse", "location_code"],
	"stock": ["warehouse", "location_code", "item_code", "qty"],
}

SAMPLE = {
	"zones": ["01 - Loja Alvalade - ITEC", "FRONT", "Front Aisle", "1", "Fast movers by the till"],
	"locations": ["01 - Loja Alvalade - ITEC", "A-01", "Aisle A Shelf 1", "FRONT", "Pick Face",
	              "500", "7890001", "Reachable without a ladder"],
	"stock": ["01 - Loja Alvalade - ITEC", "A-01", "ITEM-0001", "12"],
}

LOCATION_TYPES = ("Storage", "Pick Face", "Bulk", "Staging", "Quarantine")


# ======================================================================
# helpers
# ======================================================================
def _guard():
	from isoft_warehouse_location_management.isoft_location_manager.page.isoft_location_manager.isoft_location_manager import (
		_require_preparer,
		_scope,
	)

	_require_preparer()
	return _scope(None)


def _kind(kind):
	if kind not in KINDS:
		frappe.throw(_("Unknown import type {0}.").format(kind))
	return kind


def _rows(rows):
	rows = frappe.parse_json(rows) if isinstance(rows, str) else rows
	if not isinstance(rows, list):
		frappe.throw(_("Expected a list of rows."))
	return rows


def _num(value, label, idx, problems, minimum=None, required=False):
	"""A number, or a clear complaint about what was actually in the cell."""
	raw = cstr(value).strip()
	if raw == "":
		if required:
			problems.append(_("row {0}: {1} is required").format(idx, label))
		return None
	# spreadsheets export 1 234,50 and 1,234.50 depending on the locale they were saved in
	cleaned = raw.replace(" ", "").replace(" ", "")
	if "," in cleaned and "." in cleaned:
		cleaned = cleaned.replace(",", "") if cleaned.rfind(".") > cleaned.rfind(",") else cleaned.replace(".", "").replace(",", ".")
	elif "," in cleaned:
		cleaned = cleaned.replace(",", ".")
	try:
		out = float(cleaned)
	except ValueError:
		problems.append(_("row {0}: {1} is not a number ({2})").format(idx, label, raw))
		return None
	if minimum is not None and out < minimum:
		problems.append(_("row {0}: {1} cannot be less than {2}").format(idx, label, minimum))
		return None
	return out


# ======================================================================
# templates and export
# ======================================================================
@frappe.whitelist()
def template(kind):
	"""An empty sheet with the right columns, and one row showing the shape."""
	_guard()
	kind = _kind(kind)
	return {"columns": COLUMNS[kind], "sample": SAMPLE[kind]}


@frappe.whitelist()
def export_rows(kind, warehouse=None):
	"""What is there now, in exactly the shape the importer accepts."""
	scope = _guard()
	kind = _kind(kind)

	def in_scope(wh):
		return scope is None or wh in scope

	out = []
	if kind == "zones":
		for z in frappe.get_all(
			"Warehouse Zone",
			filters={"warehouse": warehouse} if warehouse else {},
			fields=["warehouse", "zone_code", "zone_name", "sequence", "description"],
			order_by="warehouse asc, sequence asc, zone_code asc",
			limit_page_length=0,
		):
			if in_scope(z.warehouse):
				out.append([z.warehouse, z.zone_code, z.zone_name, cint(z.sequence), z.description or ""])

	elif kind == "locations":
		filters = {"is_unassigned": 0}
		if warehouse:
			filters["warehouse"] = warehouse
		for l in frappe.get_all(
			"Warehouse Location",
			filters=filters,
			fields=["warehouse", "location_code", "location_name", "zone", "location_type",
			        "max_qty", "barcode", "description"],
			order_by="warehouse asc, location_code asc",
			limit_page_length=0,
		):
			if not in_scope(l.warehouse):
				continue
			zone_code = frappe.db.get_value("Warehouse Zone", l.zone, "zone_code") if l.zone else ""
			out.append([l.warehouse, l.location_code, l.location_name or "", zone_code or "",
			            l.location_type or "", flt(l.max_qty) or "", l.barcode or "", l.description or ""])

	else:
		rows = frappe.get_all(
			"Location Stock",
			filters={"warehouse": warehouse} if warehouse else {},
			fields=["warehouse", "location", "item_code", "qty"],
			order_by="warehouse asc, location asc, item_code asc",
			limit_page_length=0,
		)
		codes = {}
		for r in rows:
			if not in_scope(r.warehouse) or flt(r.qty) <= 0:
				continue
			meta = codes.get(r.location)
			if meta is None:
				meta = frappe.db.get_value(
					"Warehouse Location", r.location, ["location_code", "is_unassigned"], as_dict=True
				) or frappe._dict()
				codes[r.location] = meta
			if meta.get("is_unassigned"):
				continue          # the remainder is derived; exporting it would re-import as a claim
			out.append([r.warehouse, meta.get("location_code"), r.item_code, flt(r.qty)])

	return {"columns": COLUMNS[kind], "rows": out}


# ======================================================================
# import
# ======================================================================
# Every row is checked before any row is written. `check` is the dry run the screen shows
# first; `apply` re-checks and only then commits, so a file cannot half-land because the
# warehouse changed between looking and pressing the button.


def _check_zones(rows, scope):
	problems, plan = [], []
	seen = set()
	for i, r in enumerate(rows, start=1):
		wh = cstr(r.get("warehouse")).strip()
		code = cstr(r.get("zone_code")).strip().upper()
		if not wh or not code:
			problems.append(_("row {0}: warehouse and zone code are both required").format(i))
			continue
		if not frappe.db.exists("Warehouse", wh):
			problems.append(_("row {0}: no warehouse called {1}").format(i, wh))
			continue
		if frappe.get_cached_value("Warehouse", wh, "is_group"):
			problems.append(_("row {0}: {1} is a group warehouse — zones belong to a leaf").format(i, wh))
			continue
		if scope is not None and wh not in scope:
			problems.append(_("row {0}: {1} is not in your scope").format(i, wh))
			continue
		if (wh, code) in seen:
			problems.append(_("row {0}: {1} appears twice in this file").format(i, code))
			continue
		seen.add((wh, code))
		# a cell that could not be read is a reason to leave the row out of the plan, not
		# to quietly substitute a zero — the preview has to show what would really happen
		before = len(problems)
		_num(r.get("sequence"), _("sequence"), i, problems, minimum=0)
		if len(problems) > before:
			continue
		existing = frappe.db.get_value("Warehouse Zone", {"warehouse": wh, "zone_code": code}, "name")
		plan.append({
			"row": i, "action": "update" if existing else "create", "name": existing,
			"warehouse": wh, "zone_code": code,
			"zone_name": cstr(r.get("zone_name")).strip() or code.title(),
			"sequence": cint(flt(cstr(r.get("sequence")).strip() or 0)),
			"description": cstr(r.get("description")).strip(),
		})
	return plan, problems


def _check_locations(rows, scope):
	from isoft_warehouse_location_management.isoft_location_manager.doctype.warehouse_location.warehouse_location import (
		UNASSIGNED_CODE,
	)

	problems, plan = [], []
	seen = set()
	for i, r in enumerate(rows, start=1):
		wh = cstr(r.get("warehouse")).strip()
		code = cstr(r.get("location_code")).strip().upper()
		if not wh or not code:
			problems.append(_("row {0}: warehouse and location code are both required").format(i))
			continue
		if not frappe.db.exists("Warehouse", wh):
			problems.append(_("row {0}: no warehouse called {1}").format(i, wh))
			continue
		if frappe.get_cached_value("Warehouse", wh, "is_group"):
			problems.append(_("row {0}: {1} is a group warehouse — locations belong to a leaf").format(i, wh))
			continue
		if scope is not None and wh not in scope:
			problems.append(_("row {0}: {1} is not in your scope").format(i, wh))
			continue
		if code == UNASSIGNED_CODE:
			problems.append(_("row {0}: {1} is the name of unassigned stock").format(i, code))
			continue
		if (wh, code) in seen:
			problems.append(_("row {0}: {1} appears twice in this file").format(i, code))
			continue
		seen.add((wh, code))

		zone_code = cstr(r.get("zone")).strip().upper()
		zone = None
		if zone_code:
			zone = frappe.db.get_value("Warehouse Zone", {"warehouse": wh, "zone_code": zone_code}, "name")
			if not zone:
				problems.append(
					_("row {0}: {1} has no zone {2} — import the zones first").format(i, wh, zone_code)
				)
				continue

		ltype = cstr(r.get("location_type")).strip()
		if ltype and ltype not in LOCATION_TYPES:
			problems.append(
				_("row {0}: {1} is not a location type ({2})").format(i, ltype, ", ".join(LOCATION_TYPES))
			)
			continue

		before = len(problems)
		max_qty = _num(r.get("max_qty"), _("capacity"), i, problems, minimum=0)
		if len(problems) > before:
			continue
		existing = frappe.db.get_value("Warehouse Location", {"warehouse": wh, "location_code": code}, "name")
		plan.append({
			"row": i, "action": "update" if existing else "create", "name": existing,
			"warehouse": wh, "location_code": code,
			"location_name": cstr(r.get("location_name")).strip() or code,
			"zone": zone, "location_type": ltype or "Storage",
			"max_qty": max_qty or 0, "barcode": cstr(r.get("barcode")).strip(),
			"description": cstr(r.get("description")).strip(),
		})
	return plan, problems


def _check_stock(rows, scope):
	from isoft_warehouse_location_management.isoft_location_manager.doctype.location_stock.location_stock import (
		bin_qty,
		get_balance,
	)

	problems, plan = [], []
	# a file may name the same location and item twice; the last word wins, but say so
	claimed = {}
	for i, r in enumerate(rows, start=1):
		wh = cstr(r.get("warehouse")).strip()
		code = cstr(r.get("location_code")).strip().upper()
		item = cstr(r.get("item_code")).strip()
		if not wh or not code or not item:
			problems.append(_("row {0}: warehouse, location and item are all required").format(i))
			continue
		if scope is not None and wh not in scope:
			problems.append(_("row {0}: {1} is not in your scope").format(i, wh))
			continue
		if not frappe.db.exists("Item", item):
			problems.append(_("row {0}: no item called {1}").format(i, item))
			continue

		loc = frappe.db.get_value(
			"Warehouse Location", {"warehouse": wh, "location_code": code},
			["name", "is_active", "is_unassigned"], as_dict=True
		)
		if not loc:
			problems.append(_("row {0}: {1} has no location {2}").format(i, wh, code))
			continue
		if loc.is_unassigned:
			problems.append(
				_("row {0}: unassigned stock is what is left over — it cannot be imported into").format(i)
			)
			continue
		if not loc.is_active:
			problems.append(_("row {0}: location {1} is not active").format(i, code))
			continue

		qty = _num(r.get("qty"), _("qty"), i, problems, minimum=0, required=True)
		if qty is None:
			continue

		key = (loc.name, item)
		if key in claimed:
			problems.append(
				_("row {0}: {1} on {2} is already set by row {3}").format(i, item, code, claimed[key])
			)
			continue
		claimed[key] = i

		plan.append({
			"row": i, "warehouse": wh, "location": loc.name, "location_code": code,
			"item_code": item, "qty": qty,
			"was": get_balance(loc.name, item),
		})

	# a location cannot be given more of an item than the warehouse holds
	wanted = {}
	for p in plan:
		wanted.setdefault((p["warehouse"], p["item_code"]), []).append(p)
	for (wh, item), group in wanted.items():
		on_hand = bin_qty(wh, item)
		# everything this file does not mention stays where it is
		others = flt(
			frappe.db.sql(
				"""select sum(qty) from `tabLocation Stock`
				   where warehouse=%s and item_code=%s and location not in %s""",
				(wh, item, tuple(p["location"] for p in group) or ("",)),
			)[0][0]
		)
		asked = sum(flt(p["qty"]) for p in group)
		if asked + others > on_hand + 0.001:
			problems.append(
				_("{0} in {1}: the file places {2} but the warehouse holds {3}"
				  " ({4} is already on locations this file does not mention)").format(
					item, wh, asked, on_hand, others
				)
			)
	return plan, problems


CHECKERS = {"zones": _check_zones, "locations": _check_locations, "stock": _check_stock}


@frappe.whitelist()
def check(kind, rows):
	"""Dry run: what would happen, and everything wrong with the file."""
	scope = _guard()
	kind = _kind(kind)
	plan, problems = CHECKERS[kind](_rows(rows), scope)
	summary = {"create": 0, "update": 0, "set": 0}
	for p in plan:
		summary[p.get("action", "set")] = summary.get(p.get("action", "set"), 0) + 1
	return {
		"kind": kind,
		"ok": not problems,
		"rows": len(plan),
		"problems": problems,
		"summary": summary,
		"preview": plan[:20],
	}


@frappe.whitelist()
def apply(kind, rows):
	"""Write the file, or write nothing at all."""
	scope = _guard()
	kind = _kind(kind)
	plan, problems = CHECKERS[kind](_rows(rows), scope)
	if problems:
		frappe.throw(
			_("Nothing was imported — {0} problem(s) to fix first:<br>{1}").format(
				len(problems), "<br>".join(problems[:15])
			)
		)

	done = {"created": 0, "updated": 0, "placed": 0, "returned": 0}

	if kind == "zones":
		for p in plan:
			doc = frappe.get_doc("Warehouse Zone", p["name"]) if p["name"] else frappe.new_doc("Warehouse Zone")
			doc.update({
				"warehouse": p["warehouse"], "zone_code": p["zone_code"], "zone_name": p["zone_name"],
				"sequence": p["sequence"], "description": p["description"], "is_active": 1,
			})
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)
			done["updated" if p["name"] else "created"] += 1

	elif kind == "locations":
		for p in plan:
			doc = (frappe.get_doc("Warehouse Location", p["name"]) if p["name"]
			       else frappe.new_doc("Warehouse Location"))
			doc.update({
				"warehouse": p["warehouse"], "location_code": p["location_code"],
				"location_name": p["location_name"], "zone": p["zone"],
				"location_type": p["location_type"], "max_qty": p["max_qty"],
				"barcode": p["barcode"], "description": p["description"], "is_active": 1,
			})
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)
			done["updated" if p["name"] else "created"] += 1

	else:
		from isoft_warehouse_location_management.isoft_location_manager.page.isoft_location_manager.isoft_location_manager import (
			set_location_qty,
		)

		for p in plan:
			# the board's own path: the difference comes from, or goes back to, unassigned
			# stock, and the movement is recorded either way
			r = set_location_qty(p["warehouse"], p["item_code"], p["location"], p["qty"])
			moved = flt((r or {}).get("changed"))
			if moved > 0:
				done["placed"] += moved
			elif moved < 0:
				done["returned"] += -moved
			done["updated"] += 1

	return {"ok": True, "kind": kind, "rows": len(plan), **done}
