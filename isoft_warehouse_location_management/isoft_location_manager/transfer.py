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

from isoft_warehouse_location_management.isoft_location_manager.api import (
	sort_locations,
	sort_zones,
)

KINDS = ("zones", "locations", "stock")

COLUMNS = {
	"zones": ["warehouse", "zone_code", "zone_name", "description"],
	"locations": [
		"warehouse", "location_code", "zone", "description",
	],
	"stock": ["warehouse", "location_code", "item_code", "qty"],
}

# What each column is for, in the words someone filling the sheet in would use. This is
# not decoration: a spreadsheet that has to be explained in a separate email is a
# spreadsheet that comes back wrong.
NOTES = {
	"warehouse": "The exact warehouse name, as ERPNext spells it. Must be a leaf warehouse.",
	"zone_code": "Short code, unique inside the warehouse. Upper-cased automatically.",
	"zone_name": "What people call it. Left blank, the code is used.",
	"description": "Optional. A note for whoever reads the record later.",
	"location_code": "Short code, unique inside the warehouse — the label on the rack.",
	"zone": "The zone code this location sits in. It must already exist — import zones first.",
	"item_code": "The exact item code.",
	"qty": "How much of this item sits on this location. The difference comes from, or goes "
	"back to, unassigned stock — nothing leaves the warehouse.",
}

WIDTHS = {
	"warehouse": 32, "zone_code": 14, "zone_name": 22, "description": 40,
	"location_code": 16, "zone": 14,
	"item_code": 22, "qty": 12,
}

REQUIRED = {
	"zones": ["warehouse", "zone_code"],
	"locations": ["warehouse", "location_code"],
	"stock": ["warehouse", "location_code", "item_code", "qty"],
}

SAMPLE = {
	"zones": ["01 - Loja Alvalade - ITEC", "FRONT", "Front Aisle", "Fast movers by the till"],
	"locations": ["01 - Loja Alvalade - ITEC", "A-01", "FRONT", "Reachable without a ladder"],
	"stock": ["01 - Loja Alvalade - ITEC", "A-01", "ITEM-0001", "12"],
}

LOCATION_TYPES = ("Storage", "Pick Face", "Bulk", "Staging", "Quarantine")


# ======================================================================
# helpers
# ======================================================================
def _guard():
	from isoft_warehouse_location_management.isoft_location_manager.page.isoft_location_manager.isoft_location_manager import (
		_require_manage,
		_scope,
	)

	# an import creates locations and zones, which is shaping the warehouse
	_require_manage()
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
		for z in sort_zones(frappe.get_all(
			"Warehouse Zone",
			filters={"warehouse": warehouse} if warehouse else {},
			fields=["warehouse", "zone_code", "zone_name", "description"],
			order_by="warehouse asc, zone_code asc",
			limit_page_length=0,
		)):
			if in_scope(z.warehouse):
				out.append([z.warehouse, z.zone_code, z.zone_name, z.description or ""])

	elif kind == "locations":
		filters = {"is_unassigned": 0}
		if warehouse:
			filters["warehouse"] = warehouse
		for l in sort_locations(frappe.get_all(
			"Warehouse Location",
			filters=filters,
			fields=["warehouse", "location_code", "zone", "description"],
			order_by="warehouse asc, location_code asc",
			limit_page_length=0,
		)):
			if not in_scope(l.warehouse):
				continue
			zone_code = frappe.db.get_value("Warehouse Zone", l.zone, "zone_code") if l.zone else ""
			out.append([l.warehouse, l.location_code, zone_code or "", l.description or ""])

	else:
		rows = sort_locations(frappe.get_all(
			"Location Stock",
			filters={"warehouse": warehouse} if warehouse else {},
			fields=["warehouse", "location", "item_code", "qty"],
			order_by="warehouse asc, location asc, item_code asc",
			limit_page_length=0,
		))
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


def _check_zones(rows, scope, pending=None):
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
		if len(problems) > before:
			continue
		existing = frappe.db.get_value("Warehouse Zone", {"warehouse": wh, "zone_code": code}, "name")
		plan.append({
			"row": i, "action": "update" if existing else "create", "name": existing,
			"warehouse": wh, "zone_code": code,
			"zone_name": cstr(r.get("zone_name")).strip() or code.title(),
			"description": cstr(r.get("description")).strip(),
		})
	return plan, problems


def _check_locations(rows, scope, pending=None):
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
		if zone_code:
			known = frappe.db.exists("Warehouse Zone", {"warehouse": wh, "zone_code": zone_code})
			# a zone the zones sheet of this same workbook is about to create counts as
			# existing: the sheets are applied in order, so by then it will
			coming = (wh, zone_code) in ((pending or {}).get("zones") or set())
			if not known and not coming:
				problems.append(
					_("row {0}: {1} has no zone {2} — import the zones first").format(i, wh, zone_code)
				)
				continue

		existing = frappe.db.get_value("Warehouse Location", {"warehouse": wh, "location_code": code}, "name")
		plan.append({
			"row": i, "action": "update" if existing else "create", "name": existing,
			"warehouse": wh, "location_code": code, "zone_code": zone_code,
			"description": cstr(r.get("description")).strip(),
		})
	return plan, problems


def _check_stock(rows, scope, pending=None):
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
		coming = (wh, code) in ((pending or {}).get("locations") or set())
		if not loc and not coming:
			problems.append(_("row {0}: {1} has no location {2}").format(i, wh, code))
			continue
		if loc and loc.is_unassigned:
			problems.append(
				_("row {0}: unassigned stock is what is left over — it cannot be imported into").format(i)
			)
			continue
		if loc and not loc.is_active:
			problems.append(_("row {0}: location {1} is not active").format(i, code))
			continue

		qty = _num(r.get("qty"), _("qty"), i, problems, minimum=0, required=True)
		if qty is None:
			continue

		key = (loc.name if loc else (wh, code), item)
		if key in claimed:
			problems.append(
				_("row {0}: {1} on {2} is already set by row {3}").format(i, item, code, claimed[key])
			)
			continue
		claimed[key] = i

		plan.append({
			"row": i, "warehouse": wh, "location": loc.name if loc else None,
			"location_code": code, "item_code": item, "qty": qty,
			"was": get_balance(loc.name, item) if loc else 0,
		})

	# a location cannot be given more of an item than the warehouse holds
	wanted = {}
	for p in plan:
		wanted.setdefault((p["warehouse"], p["item_code"]), []).append(p)
	for (wh, item), group in wanted.items():
		on_hand = bin_qty(wh, item)
		# everything this file does not mention stays where it is
		touched = tuple(p["location"] for p in group if p["location"]) or ("",)
		others = flt(
			frappe.db.sql(
				"""select sum(qty) from `tabLocation Stock`
				   where warehouse=%s and item_code=%s and location not in %s""",
				(wh, item, touched),
			)[0][0]
		)
		asked = sum(flt(p["qty"]) for p in group)
		if asked + others > on_hand + 0.001:
			# Naming where the rest already sits is the whole answer: a sheet only ever
			# draws from unassigned stock, so the fix is always to include a row for the
			# location it should come out of.
			held = frappe.db.sql(
				"""select wl.location_code, ls.qty from `tabLocation Stock` ls
				   join `tabWarehouse Location` wl on wl.name = ls.location
				   where ls.warehouse=%s and ls.item_code=%s and ls.location not in %s
				     and ls.qty > 0 order by ls.qty desc""",
				(wh, item, touched),
			)
			where = ", ".join("%s (%s)" % (c, flt(q)) for c, q in held[:4])
			if len(held) > 4:
				where += _(" and {0} more").format(len(held) - 4)
			problems.append(
				_("{0} in {1}: the file places {2}, but only {3} is not yet on a location."
				  " The other {4} is already on {5}. This file does not mention those, so"
				  " they stay as they are — to move stock onto another location, give the"
				  " one it comes from its own row, with its new lower quantity.").format(
					item, wh, asked, flt(on_hand - others), others, where or _("other locations")
				)
			)
	return plan, problems


CHECKERS = {"zones": _check_zones, "locations": _check_locations, "stock": _check_stock}


@frappe.whitelist()
def check(kind, rows):
	"""Dry run: what would happen, and everything wrong with the file."""
	scope = _guard()
	kind = _kind(kind)
	plan, problems = CHECKERS[kind](_rows(rows), scope, None)
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
	plan, problems = CHECKERS[kind](_rows(rows), scope, None)
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
				"description": p["description"], "is_active": 1,
			})
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)
			done["updated" if p["name"] else "created"] += 1

	elif kind == "locations":
		for p in plan:
			doc = (frappe.get_doc("Warehouse Location", p["name"]) if p["name"]
			       else frappe.new_doc("Warehouse Location"))
			# resolved now rather than at check time: the zone may have been created by an
			# earlier sheet of this same workbook
			zone = frappe.db.get_value(
				"Warehouse Zone", {"warehouse": p["warehouse"], "zone_code": p["zone_code"]}, "name"
			) if p["zone_code"] else None
			doc.update({
				"warehouse": p["warehouse"], "location_code": p["location_code"],
				"zone": zone, "description": p["description"], "is_active": 1,
			})
			# The sheet no longer carries a name or a type. On a location that already
			# exists those are left exactly as they are — a column a file does not have
			# is not an instruction to blank the field.
			if not p["name"]:
				doc.location_name = p["location_code"]
				doc.location_type = "Storage"
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)
			done["updated" if p["name"] else "created"] += 1

	else:
		from isoft_warehouse_location_management.isoft_location_manager.page.isoft_location_manager.isoft_location_manager import (
			set_location_qty,
		)

		for p in plan:
			# likewise: the location may have been created a moment ago by the locations
			# sheet of this same workbook
			location = p["location"] or frappe.db.get_value(
				"Warehouse Location",
				{"warehouse": p["warehouse"], "location_code": p["location_code"]}, "name"
			)
			if not location:
				frappe.throw(
					_("Row {0}: {1} has no location {2}.").format(
						p["row"], p["warehouse"], p["location_code"]
					)
				)
			# the board's own path: the difference comes from, or goes back to, unassigned
			# stock, and the movement is recorded either way
			r = set_location_qty(p["warehouse"], p["item_code"], location, p["qty"])
			moved = flt((r or {}).get("changed"))
			if moved > 0:
				done["placed"] += moved
			elif moved < 0:
				done["returned"] += -moved
			done["updated"] += 1

	return {"ok": True, "kind": kind, "rows": len(plan), **done}


# ======================================================================
# workbooks
# ======================================================================
# A sheet somebody has to be told how to fill in is a sheet that comes back wrong, so the
# workbook explains itself: the header says what is required, the columns are wide enough
# to read, the cells that have a fixed set of answers offer them as a dropdown, and a
# second sheet spells out every column in words.

HEADER_FILL = "FF0F766E"
REQUIRED_FILL = "FFE6FFFA"


def _sheet_title(kind):
	return {"zones": "Zones", "locations": "Locations", "stock": "Stock on locations"}[kind]


def _sheet_into(wb, kind, rows, with_sample=False):
	from openpyxl import Workbook
	from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
	from openpyxl.utils import get_column_letter
	from openpyxl.worksheet.datavalidation import DataValidation

	columns = COLUMNS[kind]
	required = REQUIRED[kind]

	if wb is None:
		wb = Workbook()
		ws = wb.active
		ws.title = _sheet_title(kind)
	else:
		ws = wb.create_sheet(_sheet_title(kind))

	head_font = Font(bold=True, color="FFFFFFFF", size=11)
	head_fill = PatternFill("solid", fgColor=HEADER_FILL)
	thin = Side(style="thin", color="FFD8E0E6")

	for c, col in enumerate(columns, start=1):
		cell = ws.cell(row=1, column=c)
		# the header carries the rule, so nobody has to look it up
		cell.value = col + (" *" if col in required else "")
		cell.font = head_font
		cell.fill = head_fill
		cell.alignment = Alignment(vertical="center", horizontal="left")
		cell.border = Border(bottom=thin)
		ws.column_dimensions[get_column_letter(c)].width = WIDTHS.get(col, 18)
	ws.row_dimensions[1].height = 22
	ws.freeze_panes = "A2"
	ws.auto_filter.ref = "A1:%s1" % get_column_letter(len(columns))

	start = 2
	if with_sample:
		for c, value in enumerate(SAMPLE[kind], start=1):
			cell = ws.cell(row=2, column=c, value=value)
			cell.font = Font(italic=True, color="FF8D99A6")
		start = 3

	for r, row in enumerate(rows or [], start=start):
		for c, value in enumerate(row, start=1):
			ws.cell(row=r, column=c, value=value)

	# quantities and capacities are numbers, and should look like numbers
	for c, col in enumerate(columns, start=1):
		if col == "qty":
			for r in range(2, ws.max_row + 1):
				ws.cell(row=r, column=c).number_format = "#,##0.###"

	# the columns with a fixed set of answers offer them, rather than being guessed at
	limit = max(ws.max_row + 200, 500)
	for col in ("qty",):
		if col in columns:
			c = get_column_letter(columns.index(col) + 1)
			dv = DataValidation(
				type="decimal", operator="greaterThanOrEqual", formula1=0, allow_blank=(col != "qty"),
				showErrorMessage=True, errorTitle="Not a quantity",
				error="This must be a number, and cannot be negative.",
			)
			ws.add_data_validation(dv)
			dv.add("%s2:%s%d" % (c, c, limit))

	return wb


def _help_sheet(wb, kind, suffix=False):
	from openpyxl.styles import Alignment, Font, PatternFill

	title = "How to fill in %s" % _sheet_title(kind) if suffix else "How to fill this in"
	ws = wb.create_sheet(title[:31])
	ws.column_dimensions["A"].width = 20
	ws.column_dimensions["B"].width = 12
	ws.column_dimensions["C"].width = 86

	ws["A1"] = _sheet_title(kind)
	ws["A1"].font = Font(bold=True, size=14)
	ws["A2"] = {
		"zones": "The parts a warehouse is divided into. Import these before locations, "
		"because a location can name one.",
		"locations": "The shelves, racks and bins themselves. A zone named here must already exist.",
		"stock": "What sits on each location. The difference comes from, or goes back to, "
		"unassigned stock — nothing leaves the warehouse.",
	}[kind]
	ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
	ws.merge_cells("A2:C2")
	ws.row_dimensions[2].height = 30

	for c, title in enumerate(("Column", "Required", "What it means"), start=1):
		cell = ws.cell(row=4, column=c, value=title)
		cell.font = Font(bold=True, color="FFFFFFFF")
		cell.fill = PatternFill("solid", fgColor=HEADER_FILL)

	for r, col in enumerate(COLUMNS[kind], start=5):
		ws.cell(row=r, column=1, value=col).font = Font(bold=True)
		ws.cell(row=r, column=2, value="yes" if col in REQUIRED[kind] else "")
		cell = ws.cell(row=r, column=3, value=NOTES.get(col, ""))
		cell.alignment = Alignment(wrap_text=True, vertical="top")

	last = 5 + len(COLUMNS[kind]) + 1
	ws.cell(row=last, column=1, value="Before you import").font = Font(bold=True)
	ws.cell(
		row=last + 1, column=1,
		value="The whole file is checked before anything is written. If any row is wrong, "
		"nothing is imported at all — fix the rows it lists and send the same file again.",
	).alignment = Alignment(wrap_text=True, vertical="top")
	ws.merge_cells(start_row=last + 1, start_column=1, end_row=last + 1, end_column=3)
	ws.row_dimensions[last + 1].height = 30
	return ws


def _respond(wb, filename):
	from io import BytesIO

	buf = BytesIO()
	wb.save(buf)
	frappe.response["filename"] = filename
	frappe.response["filecontent"] = buf.getvalue()
	frappe.response["type"] = "binary"


def _kinds(kinds):
	"""One or several kinds, in the order a warehouse has to be described."""
	if isinstance(kinds, str):
		kinds = frappe.parse_json(kinds) if kinds.strip().startswith("[") else [kinds]
	wanted = [k for k in KINDS if k in set(kinds or [])]
	if not wanted:
		frappe.throw(_("Choose at least one thing to include."))
	return wanted


def _multi_workbook(kinds, rows_by_kind, with_sample=False):
	"""A sheet per kind, in dependency order, with the help sheets after them."""
	wb = None
	for kind in kinds:
		wb = _sheet_into(wb, kind, rows_by_kind.get(kind) or [], with_sample)
	for kind in kinds:
		_help_sheet(wb, kind, suffix=len(kinds) > 1)
	return wb


@frappe.whitelist()
def download_template(kinds="locations"):
	"""Empty sheets with the right columns, an example row each, and how to fill them in."""
	_guard()
	kinds = _kinds(kinds)
	wb = _multi_workbook(kinds, {}, with_sample=True)
	name = "ilm-template.xlsx" if len(kinds) > 1 else "ilm-%s-template.xlsx" % kinds[0]
	_respond(wb, name)


@frappe.whitelist()
def download_export(kinds="locations", warehouse=None):
	"""What is there now, in exactly the workbook the importer accepts."""
	_guard()
	kinds = _kinds(kinds)
	rows_by_kind = {k: export_rows(k, warehouse)["rows"] for k in kinds}
	wb = _multi_workbook(kinds, rows_by_kind)
	name = "ilm-export.xlsx" if len(kinds) > 1 else "ilm-%s.xlsx" % kinds[0]
	_respond(wb, name)


def _kind_of(header):
	"""Which of the three a sheet is, judged by its own columns.

	The distinguishing column is enough and does not depend on order: only stock names an
	item, only zones name a zone code of their own, and what is left with a location code
	is the locations sheet.
	"""
	cols = set(header)
	if "item_code" in cols:
		return "stock"
	if "zone_code" in cols:
		return "zones"
	if "location_code" in cols:
		return "locations"
	return None


def _header_key(h):
	return cstr(h).strip().lower().replace("*", "").replace(" ", "_").strip("_")


def _table_to_rows(table):
	table = [r for r in (table or []) if any(cstr(c).strip() for c in r)]
	if not table:
		return None, []
	header = [_header_key(h) for h in table[0]]
	kind = _kind_of(header)
	if not kind:
		return None, []
	rows = []
	for line in table[1:]:
		row = {}
		for i, h in enumerate(header):
			if h:
				row[h] = line[i] if i < len(line) else ""
		rows.append(row)
	return kind, rows


@frappe.whitelist()
def read_upload(content, filename=None):
	"""Turn an uploaded workbook into sheets of rows, each one identified by its header.

	A workbook may hold zones, locations and stock at once — that is what the export
	produces — so every sheet is read and identified on its own. Sheets that are not one
	of the three are skipped rather than complained about: a working spreadsheet usually
	has a scratch tab in it.

	`.csv` is accepted too, because somebody will always send one, and refusing it
	teaches them nothing.
	"""
	_guard()
	import base64

	raw = content
	if isinstance(raw, str):
		if raw[:5] == "data:" and "," in raw[:128]:
			raw = raw.split(",", 1)[1]
		raw = base64.b64decode(raw)

	tables = []
	if (filename or "").lower().endswith(".csv"):
		import csv
		import io

		text = raw.decode("utf-8-sig", errors="replace")
		tables.append([r for r in csv.reader(io.StringIO(text))])
	else:
		import io

		from openpyxl import load_workbook

		wb = load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
		for ws in wb.worksheets:
			tables.append([[c for c in row] for row in ws.iter_rows(values_only=True)])

	sheets = []
	for table in tables:
		kind, rows = _table_to_rows(table)
		if kind and rows:
			sheets.append({"kind": kind, "rows": rows, "count": len(rows)})

	if not sheets:
		frappe.throw(
			_("Nothing in that file looks like zones, locations or stock. "
			  "The first row of a sheet has to be the column names — start from a template.")
		)

	# always in the order a warehouse has to be described
	sheets.sort(key=lambda x: KINDS.index(x["kind"]))
	return {"sheets": sheets, "count": sum(s["count"] for s in sheets)}


@frappe.whitelist()
def check_sheets(sheets):
	"""Dry run every sheet, in order, and report them together."""
	scope = _guard()
	sheets = frappe.parse_json(sheets) if isinstance(sheets, str) else sheets
	sheets = sorted(sheets or [], key=lambda x: KINDS.index(_kind(x.get("kind"))))
	out, ok_all = [], True
	# what the sheets before this one will have created by the time it is applied
	pending = {"zones": set(), "locations": set()}
	for sheet in sheets:
		kind = _kind(sheet.get("kind"))
		plan, problems = CHECKERS[kind](sheet.get("rows") or [], scope, pending)
		if kind == "zones":
			pending["zones"] |= {(p["warehouse"], p["zone_code"]) for p in plan}
		elif kind == "locations":
			pending["locations"] |= {(p["warehouse"], p["location_code"]) for p in plan}
		summary = {"create": 0, "update": 0, "set": 0}
		for p in plan:
			key = p.get("action", "set")
			summary[key] = summary.get(key, 0) + 1
		ok_all = ok_all and not problems
		out.append({
			"kind": kind, "title": _sheet_title(kind), "rows": len(plan),
			"read": len(sheet.get("rows") or []), "problems": problems, "summary": summary,
		})
	return {"ok": ok_all, "sheets": out,
	        "rows": sum(s["rows"] for s in out),
	        "problems": sum(len(s["problems"]) for s in out)}


@frappe.whitelist()
def apply_sheets(sheets):
	"""Write every sheet, or write nothing at all.

	Checked as a whole first: locations that name a zone in the same file are only valid
	once that zone exists, so the sheets are applied in order — but a problem anywhere
	stops all of it, including the sheets that would have been fine.
	"""
	_guard()
	sheets = frappe.parse_json(sheets) if isinstance(sheets, str) else sheets
	sheets = sorted(sheets or [], key=lambda x: KINDS.index(_kind(x.get("kind"))))

	report = check_sheets(sheets)
	if not report["ok"]:
		lines = []
		for s in report["sheets"]:
			lines += ["<b>%s</b>: %s" % (s["title"], p) for p in s["problems"][:10]]
		frappe.throw(
			_("Nothing was imported — {0} problem(s) to fix first:<br>{1}").format(
				report["problems"], "<br>".join(lines[:15])
			)
		)

	done = []
	for sheet in sheets:
		kind = _kind(sheet.get("kind"))
		r = apply(kind, frappe.as_json(sheet.get("rows") or []))
		r["title"] = _sheet_title(kind)
		done.append(r)
	return {"ok": True, "sheets": done}


# ======================================================================
# the Locations board, as a workbook
# ======================================================================
# Not the import shape. The sheets above are written to be sent back; these are written
# to be read, printed and pivoted: one row per item on a shelf, one sheet for the shelves
# themselves with the empty ones kept (an empty shelf is a fact worth exporting), one for
# what is not put away, and a cover sheet that says what was asked for — because a
# spreadsheet that has been mailed on no longer remembers which warehouse, zone or search
# it came from. Totals are SUBTOTAL, so they follow the reader's filter instead of
# quietly contradicting it.

REPORT_HEADER_FILL = "FF0F766E"
REPORT_TITLE_COLOR = "FF0F172A"
REPORT_MUTED_COLOR = "FF64748B"
REPORT_RULE_COLOR = "FFD8E0E6"
QTY_FORMAT = "#,##0.###"
INT_FORMAT = "#,##0"


def _report_sheet(wb, title, subtitle, columns, rows, tab_color=None, total_label=None):
	"""One sheet: a title block, a styled header, the rows, and a total that follows the filter.

	`columns` are dicts of label / key / width / fmt. A column with a `fmt` is a number,
	which decides its alignment, its format and whether the total row sums it.
	"""
	from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
	from openpyxl.utils import get_column_letter
	from openpyxl.worksheet.properties import PageSetupProperties

	ws = wb.create_sheet(title[:31])
	if tab_color:
		ws.sheet_properties.tabColor = tab_color
	# every row is ruled by its own bottom border, so the grid underneath is noise
	ws.sheet_view.showGridLines = False

	last_col = get_column_letter(len(columns))
	ws["A1"] = title
	ws["A1"].font = Font(bold=True, size=14, color=REPORT_TITLE_COLOR)
	ws["A2"] = subtitle
	ws["A2"].font = Font(size=9, italic=True, color=REPORT_MUTED_COLOR)
	ws.merge_cells("A1:%s1" % last_col)
	ws.merge_cells("A2:%s2" % last_col)
	ws.row_dimensions[1].height = 20
	ws.row_dimensions[3].height = 6

	head_row = 4
	head_font = Font(bold=True, size=10, color="FFFFFFFF")
	head_fill = PatternFill("solid", fgColor=REPORT_HEADER_FILL)
	rule = Side(style="thin", color=REPORT_RULE_COLOR)
	for c, col in enumerate(columns, start=1):
		cell = ws.cell(row=head_row, column=c, value=col["label"])
		cell.font = head_font
		cell.fill = head_fill
		cell.alignment = Alignment(
			vertical="center", horizontal="right" if col.get("fmt") else "left"
		)
		ws.column_dimensions[get_column_letter(c)].width = col.get("width", 18)
	ws.row_dimensions[head_row].height = 20

	first = head_row + 1
	for r, row in enumerate(rows or [], start=first):
		for c, col in enumerate(columns, start=1):
			cell = ws.cell(row=r, column=c, value=row.get(col["key"]))
			cell.border = Border(bottom=rule)
			if col.get("fmt"):
				cell.number_format = col["fmt"]
				cell.alignment = Alignment(horizontal="right")
	last = first + len(rows or []) - 1

	ws.freeze_panes = "A%d" % first
	ws.auto_filter.ref = "A%d:%s%d" % (head_row, last_col, max(last, first))

	# it will be printed, so it should print like a report: wide, on as many pages as it
	# takes, with the header repeated and the page number at the foot of each
	ws.print_title_rows = "%d:%d" % (head_row, head_row)
	ws.page_setup.orientation = "landscape"
	ws.page_setup.fitToWidth = 1
	ws.page_setup.fitToHeight = 0
	ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
	ws.oddFooter.right.text = "&P / &N"
	ws.oddFooter.left.text = subtitle[:120]

	if rows and total_label:
		top = Side(style="medium", color=REPORT_HEADER_FILL)
		trow = last + 1
		for c, col in enumerate(columns, start=1):
			cell = ws.cell(row=trow, column=c)
			cell.font = Font(bold=True)
			cell.border = Border(top=top)
			if c == 1:
				cell.value = total_label
			elif col.get("fmt"):
				letter = get_column_letter(c)
				cell.value = "=SUBTOTAL(109,{0}{1}:{0}{2})".format(letter, first, last)
				cell.number_format = col["fmt"]
				cell.alignment = Alignment(horizontal="right")
	elif not rows:
		cell = ws.cell(row=first, column=1, value=_("Nothing to show here."))
		cell.font = Font(italic=True, color=REPORT_MUTED_COLOR)
	return ws


def _cover_sheet(wb, lines, figures):
	"""What was asked for, and what came back — so the file still says so next month."""
	from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

	ws = wb.active
	ws.title = _("Summary")
	ws.sheet_properties.tabColor = REPORT_HEADER_FILL
	ws.column_dimensions["A"].width = 34
	ws.column_dimensions["B"].width = 30
	ws.sheet_view.showGridLines = False

	ws["A1"] = _("Warehouse locations")
	ws["A1"].font = Font(bold=True, size=16, color=REPORT_TITLE_COLOR)
	ws.merge_cells("A1:B1")
	ws.row_dimensions[1].height = 24

	r = 3
	for label, value in lines:
		ws.cell(row=r, column=1, value=label).font = Font(bold=True, size=10)
		ws.cell(row=r, column=2, value=value).alignment = Alignment(horizontal="left")
		r += 1

	r += 1
	head = ws.cell(row=r, column=1, value=_("What is in this workbook"))
	head.font = Font(bold=True, size=10, color="FFFFFFFF")
	head.fill = PatternFill("solid", fgColor=REPORT_HEADER_FILL)
	ws.cell(row=r, column=2).fill = PatternFill("solid", fgColor=REPORT_HEADER_FILL)
	rule = Side(style="thin", color=REPORT_RULE_COLOR)
	r += 1
	for label, value, fmt in figures:
		ws.cell(row=r, column=1, value=label).border = Border(bottom=rule)
		cell = ws.cell(row=r, column=2, value=value)
		cell.number_format = fmt
		cell.alignment = Alignment(horizontal="left")
		cell.border = Border(bottom=rule)
		r += 1
	return ws


def _locations_report(warehouse=None, zone=None, search=None, hide_zero=1, locations=None):
	"""Everything both renderings need, gathered once.

	`locations` narrows it to a chosen few — the selection on the board, or the single
	location whose form asked for it. Loose stock belongs to a warehouse rather than to
	any location, so it is left out when the answer is about particular shelves.
	"""
	from isoft_warehouse_location_management.isoft_location_manager.api import natural_key
	from isoft_warehouse_location_management.isoft_location_manager.page.isoft_location_manager.isoft_location_manager import (
		_require_access,
		_scope,
		_scope_label,
		get_locations_with_items,
		get_unassigned,
	)

	_require_access()
	search = (search or "").strip()
	zone = (zone or "").strip()
	hide_zero = cint(hide_zero)
	chosen = frappe.parse_json(locations) if isinstance(locations, str) else locations
	chosen = [c for c in (chosen or []) if c]

	secs = get_locations_with_items(warehouse=warehouse, search=search)
	zone_label = _("All zones")
	if zone == "__none__":
		secs = [s for s in secs if not s.get("zone")]
		zone_label = _("Not in a zone")
	elif zone:
		secs = [s for s in secs if s.get("zone") == zone]
		zone_label = frappe.db.get_value("Warehouse Zone", zone, "zone_name") or zone

	if chosen:
		picked = set(chosen)
		secs = [s for s in secs if s.get("location") in picked]

	# the board groups its columns by zone, naturally ordered, with the unfiled ones last;
	# a sheet in a different order from the screen it was taken from is a sheet nobody
	# trusts. sorted() is stable, so inside a zone the server's pick order survives.
	secs = sorted(
		secs,
		key=lambda s: (
			0 if s.get("zone") else 1,
			natural_key(s.get("zone_name") or s.get("zone_code") or ""),
		),
	)

	loose = (
		{"items": []}
		if chosen
		else get_unassigned(warehouse=warehouse, search=search, start=0, limit=100000)
	)

	# one lookup for every unit of measure on the sheet, rather than one per row
	codes = {i.get("item_code") for s in secs for i in s.get("items") or []}
	uoms = {}
	if codes:
		uoms = {
			r.name: r.stock_uom
			for r in frappe.get_all(
				"Item", filters={"name": ["in", list(codes)]}, fields=["name", "stock_uom"],
				limit_page_length=0,
			)
		}

	no_zone = _("Not in a zone")
	stock_rows, location_rows = [], []
	for s in secs:
		zname = s.get("zone_name") or s.get("zone_code") or no_zone
		kept = [
			i for i in (s.get("items") or [])
			if not hide_zero or abs(flt(i.get("qty"))) > 0.000001
		]
		location_rows.append({
			"zone": zname,
			"code": s.get("location_code"),
			"name": s.get("location_name"),
			"warehouse": s.get("warehouse"),
			# the count has to mean the rows on the other sheet, or the two disagree
			"items": len(kept),
			"qty": flt(s.get("total_qty")),
		})
		for i in kept:
			stock_rows.append({
				"zone": zname,
				"code": s.get("location_code"),
				"name": s.get("location_name"),
				"warehouse": s.get("warehouse"),
				"item_code": i.get("item_code"),
				"item_name": i.get("item_name"),
				"barcode": i.get("barcode"),
				"qty": flt(i.get("qty")),
				"uom": uoms.get(i.get("item_code")),
			})

	loose_rows = [
		{
			"warehouse": r.get("warehouse"),
			"item_code": r.get("item_code"),
			"item_name": r.get("item_name"),
			"barcode": r.get("barcode"),
			"qty": flt(r.get("qty")),
			"uom": r.get("stock_uom"),
		}
		for r in (loose.get("items") or [])
	]

	scope_label = _scope_label(warehouse, _scope(warehouse))
	asked = [
		(_("Warehouse"), scope_label),
		(_("Zone"), zone_label),
		(_("Search"), search or _("Everything")),
		(_("Empty lines"), _("Hidden") if hide_zero else _("Included")),
	]
	if chosen:
		# not "Locations": the figures below already count those, and a cover with the
		# same word against two different numbers is a cover nobody reads twice
		asked.append((
			_("Selection"),
			chosen[0] if len(chosen) == 1 else _("{0} chosen on the board").format(len(chosen)),
		))
	asked += [
		(_("Exported"), frappe.utils.format_datetime(frappe.utils.now())),
		(_("By"), frappe.session.user),
	]

	shelved = sum(r["qty"] for r in stock_rows)
	units_loose = sum(r["qty"] for r in loose_rows)
	total_units = shelved + units_loose
	figures = [
		(_("Locations"), len(location_rows), INT_FORMAT),
		(_("Locations holding stock"), len([r for r in location_rows if r["items"]]), INT_FORMAT),
		(_("Empty locations"), len([r for r in location_rows if not r["items"]]), INT_FORMAT),
		(_("Lines on shelves"), len(stock_rows), INT_FORMAT),
		(_("Units on shelves"), shelved, QTY_FORMAT),
	]
	if not chosen:
		figures += [
			(_("Items not put away"), len(loose_rows), INT_FORMAT),
			(_("Units not put away"), units_loose, QTY_FORMAT),
			(_("Put away"), (shelved / total_units) if total_units else 0, "0.0%"),
		]

	return {
		"asked": asked,
		"figures": figures,
		"stock_rows": stock_rows,
		"location_rows": location_rows,
		"loose_rows": loose_rows,
		"by_location": bool(chosen),
		"subtitle": " · ".join(
			"%s: %s" % (label, value) for label, value in asked if value not in (None, "")
		),
	}


STOCK_COLUMNS = (
	# the item comes first and the place it is in follows the barcode: this sheet is
	# read item by item, and the barcode is the last thing that identifies the item
	{"label": "Warehouse", "key": "warehouse", "width": 26},
	{"label": "Item", "key": "item_code", "width": 20},
	{"label": "Item name", "key": "item_name", "width": 38},
	{"label": "Barcode", "key": "barcode", "width": 18},
	{"label": "Zone", "key": "zone", "width": 20},
	{"label": "Location", "key": "code", "width": 16},
	{"label": "Location name", "key": "name", "width": 26},
	{"label": "Qty", "key": "qty", "width": 12, "fmt": QTY_FORMAT},
	{"label": "UOM", "key": "uom", "width": 9},
)

LOCATION_COLUMNS = (
	{"label": "Zone", "key": "zone", "width": 20},
	{"label": "Location", "key": "code", "width": 16},
	{"label": "Location name", "key": "name", "width": 26},
	{"label": "Warehouse", "key": "warehouse", "width": 26},
	{"label": "Items", "key": "items", "width": 10, "fmt": INT_FORMAT},
	{"label": "Units", "key": "qty", "width": 14, "fmt": QTY_FORMAT},
)

LOOSE_COLUMNS = (
	{"label": "Warehouse", "key": "warehouse", "width": 26},
	{"label": "Item", "key": "item_code", "width": 20},
	{"label": "Item name", "key": "item_name", "width": 38},
	{"label": "Barcode", "key": "barcode", "width": 18},
	{"label": "Qty", "key": "qty", "width": 12, "fmt": QTY_FORMAT},
	{"label": "UOM", "key": "uom", "width": 9},
)


def _cols(spec):
	"""The column spec with its labels translated at call time."""
	return [dict(c, label=_(c["label"])) for c in spec]


def _locations_workbook(data):
	from openpyxl import Workbook

	wb = Workbook()
	_cover_sheet(wb, data["asked"], data["figures"])
	_report_sheet(wb, _("Stock by location"), data["subtitle"], _cols(STOCK_COLUMNS),
		data["stock_rows"], tab_color="FF0F766E", total_label=_("Total"))
	_report_sheet(wb, _("Locations"), data["subtitle"], _cols(LOCATION_COLUMNS),
		data["location_rows"], tab_color="FF0EA5E9", total_label=_("Total"))
	if not data["by_location"]:
		_report_sheet(wb, _("Not put away"), data["subtitle"], _cols(LOOSE_COLUMNS),
			data["loose_rows"], tab_color="FFB45309", total_label=_("Total"))
	return wb


def _pdf_table(title, columns, rows):
	"""One table, as the page prints it: a heading, a ruled header and a total."""
	esc = frappe.utils.escape_html

	def cell(row, col):
		value = row.get(col["key"])
		if col.get("fmt"):
			return frappe.format_value(flt(value), {"fieldtype": "Float", "precision": 3})
		return esc(value or "")

	if not rows:
		return "<h2>{0}</h2><p class='none'>{1}</p>".format(esc(title), _("Nothing to show here."))

	head = "".join(
		"<th class='{0}'>{1}</th>".format("num" if c.get("fmt") else "", esc(c["label"]))
		for c in columns
	)
	body = "".join(
		"<tr>{0}</tr>".format("".join(
			"<td class='{0}'>{1}</td>".format("num" if c.get("fmt") else "", cell(r, c))
			for c in columns
		))
		for r in rows
	)
	foot = "".join(
		"<td class='num'>{0}</td>".format(
			frappe.format_value(sum(flt(r.get(c["key"])) for r in rows),
				{"fieldtype": "Float", "precision": 3})
		)
		if c.get("fmt")
		else "<td>{0}</td>".format(esc(_("Total")) if c is columns[0] else "")
		for c in columns
	)
	return (
		"<h2>{title}</h2><table><thead><tr>{head}</tr></thead>"
		"<tbody>{body}</tbody><tfoot><tr>{foot}</tr></tfoot></table>"
	).format(title=esc(title), head=head, body=body, foot=foot)


def _locations_html(data):
	"""The same report as a page to read rather than a sheet to work in."""
	esc = frappe.utils.escape_html
	asked = "".join(
		"<div><span>{0}</span><b>{1}</b></div>".format(esc(label), esc(value))
		for label, value in data["asked"]
	)
	figures = "".join(
		"<div><span>{0}</span><b>{1}</b></div>".format(
			esc(label),
			"{0:.1f}%".format(value * 100) if fmt == "0.0%"
			else frappe.format_value(value, {"fieldtype": "Float", "precision": 0 if fmt == INT_FORMAT else 3}),
		)
		for label, value, fmt in data["figures"]
	)
	tables = _pdf_table(_("Stock by location"), _cols(STOCK_COLUMNS), data["stock_rows"])
	tables += _pdf_table(_("Locations"), _cols(LOCATION_COLUMNS), data["location_rows"])
	if not data["by_location"]:
		tables += _pdf_table(_("Not put away"), _cols(LOOSE_COLUMNS), data["loose_rows"])

	html = """<!doctype html><html><head><meta charset="utf-8"><style>
		@page {{ margin: 12mm 10mm; }}
		body {{ font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
			font-size: 8.5pt; color: #0f172a; }}
		h1 {{ font-size: 15pt; margin: 0 0 2mm; }}
		h2 {{ font-size: 11pt; margin: 6mm 0 2mm; padding-bottom: 1mm;
			border-bottom: 1.2pt solid #0f766e; }}
		.facts {{ display: flex; flex-wrap: wrap; gap: 0 6mm; margin-bottom: 4mm; }}
		.facts > div {{ min-width: 52mm; padding: 1mm 0; border-bottom: .4pt solid #e2e8f0; }}
		.facts span {{ color: #64748b; margin-right: 2mm; }}
		table {{ width: 100%; border-collapse: collapse; }}
		th {{ background: #0f766e; color: #fff; text-align: left; padding: 1.6mm 1.6mm;
			font-size: 8pt; }}
		td {{ padding: 1.4mm 1.6mm; border-bottom: .4pt solid #e2e8f0; }}
		th.num, td.num {{ text-align: right; white-space: nowrap; }}
		tfoot td {{ font-weight: 700; border-top: 1pt solid #0f766e; border-bottom: 0; }}
		thead {{ display: table-header-group; }}
		tr {{ page-break-inside: avoid; }}
		.none {{ color: #64748b; font-style: italic; }}
		.sub {{ color: #64748b; font-size: 7.5pt; margin-bottom: 4mm; }}
	</style></head><body>
		<h1>{title}</h1>
		<div class="sub">{subtitle}</div>
		<div class="facts">{asked}{figures}</div>
		{tables}
	</body></html>""".format(
		title=esc(_("Warehouse locations")), subtitle=esc(data["subtitle"]),
		asked=asked, figures=figures, tables=tables,
	)

	return html


def _locations_pdf(data):
	from frappe.utils.pdf import get_pdf

	return get_pdf(_locations_html(data), {"orientation": "Landscape"})


@frappe.whitelist()
def download_locations(warehouse=None, zone=None, search=None, hide_zero=1, locations=None, fmt="xlsx"):
	"""The Locations screen as it is on screen right now, as a workbook or a PDF.

	`hide_zero` drops the lines a location holds nothing of. The board keeps showing
	them — a shelf that an item has been emptied off is still that item's shelf, and
	seeing the zero is how you know — but in a workbook they are rows to scroll past,
	so they are left out unless they are asked for.
	"""
	data = _locations_report(warehouse, zone, search, hide_zero, locations)
	stamp = frappe.utils.nowdate()
	if (fmt or "xlsx").lower() == "pdf":
		frappe.local.response.filename = "ilm-locations-%s.pdf" % stamp
		frappe.local.response.filecontent = _locations_pdf(data)
		frappe.local.response.type = "pdf"
		return
	_respond(_locations_workbook(data), "ilm-locations-%s.xlsx" % stamp)
