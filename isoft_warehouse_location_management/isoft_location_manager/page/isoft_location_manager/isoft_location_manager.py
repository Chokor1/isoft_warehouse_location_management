# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, flt

from isoft_warehouse_location_management.isoft_location_manager.doctype.warehouse_location.warehouse_location import UNASSIGNED_CODE

# Opening this app is a Location Manager's job. Everyone else still sees and chooses
# locations on the documents they already work with — that needs no role at all.
PICKING_ROLES = {"Location Manager", "System Manager"}
TOL = 1e-9


# ======================================================================
# access helpers
# ======================================================================
def _roles():
	return set(frappe.get_roles(frappe.session.user))


def _require_access():
	from isoft_warehouse_location_management.isoft_location_manager.api import require_enabled

	require_enabled()
	if not (_roles() & PICKING_ROLES):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _require_admin():
	if "System Manager" not in _roles():
		frappe.throw(_("Only System Manager can manage settings."), frappe.PermissionError)


def _require_preparer():
	if not ({"Location Manager", "System Manager"} & _roles()):
		frappe.throw(_("Only a Location Manager can do this."), frappe.PermissionError)


# ======================================================================
# warehouse scope (User Permission + parent -> child rollup)
# ======================================================================
def _descendants(warehouse):
	"""All warehouses in the subtree rooted at `warehouse` (inclusive)."""
	node = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt"], as_dict=True)
	if not node or node.lft is None:
		return {warehouse}
	names = frappe.get_all(
		"Warehouse", filters={"lft": [">=", node.lft], "rgt": ["<=", node.rgt]}, pluck="name"
	)
	return set(names) | {warehouse}


def _user_perm_set():
	"""Warehouses this user may see per ERPNext User Permissions. None => no restriction."""
	if "System Manager" in _roles():
		return None
	perms = frappe.get_all(
		"User Permission",
		filters={"user": frappe.session.user, "allow": "Warehouse"},
		pluck="for_value",
	)
	if not perms:
		return None
	allowed = set()
	for wh in perms:
		allowed |= _descendants(wh)
	return allowed


def _allowed_set():
	"""Effective base = app-enabled warehouses ∩ user-permitted. None => all."""
	from isoft_warehouse_location_management.isoft_location_manager.api import enabled_warehouse_set

	enabled = enabled_warehouse_set()
	user = _user_perm_set()
	if enabled is None:
		return user
	if user is None:
		return enabled
	return enabled & user


def _scope(selected=None):
	"""Resolve the effective warehouse set for a selected node. None => all."""
	allowed = _allowed_set()
	sel = _descendants(selected) if selected else None
	if allowed is None:
		return sel  # None (all) or the selected subtree
	if sel is None:
		return allowed
	return allowed & sel


def _wh_cond(scope, col="warehouse"):
	"""Build a SQL fragment + params restricting `col` to `scope`.

	`col` may carry a table alias — `ss.warehouse`. Each part is quoted separately,
	because backticking the whole thing makes MariaDB read it as one column name.
	"""
	quoted = ".".join("`{0}`".format(part) for part in col.split("."))
	if scope is None:
		return "", []
	if not scope:
		return " and {0} in (%s)".format(quoted), ["__none__"]
	placeholders = ",".join(["%s"] * len(scope))
	return " and {0} in ({1})".format(quoted, placeholders), list(scope)


# ======================================================================
# bootstrap
# ======================================================================
@frappe.whitelist()
def can_access_picking():
	"""Safe to call with the module off — the navbar icon asks this before showing."""
	from isoft_warehouse_location_management.isoft_location_manager.api import is_enabled

	return bool(is_enabled() and (_roles() & PICKING_ROLES))


@frappe.whitelist()
def get_context():
	_require_access()
	roles = _roles()
	return {
		"theme_color": frappe.db.get_single_value("Picking Settings", "theme_color") or "Blue",
		"is_preparer": bool({"Location Manager", "System Manager"} & roles),
		"can_manage": bool(PICKING_ROLES & roles),
		"is_admin": "System Manager" in roles,
		"user": frappe.session.user,
		"warehouses": get_warehouses(),
	}


@frappe.whitelist()
def get_enabled_warehouses():
	"""Enabled warehouse names for Isoft Location Manager (empty list = all enabled)."""
	_require_access()
	from isoft_warehouse_location_management.isoft_location_manager.api import enabled_warehouse_set

	s = enabled_warehouse_set()
	return sorted(s) if s is not None else []


@frappe.whitelist()
def get_warehouses():
	"""Allowed warehouses, ordered as a tree (by lft), for scope selectors."""
	_require_access()
	allowed = _allowed_set()
	whs = frappe.get_all(
		"Warehouse",
		fields=["name", "warehouse_name", "is_group", "parent_warehouse", "lft", "rgt"],
		order_by="lft asc",
	)
	if allowed is not None:
		whs = [w for w in whs if w.name in allowed]
	return whs


# ======================================================================
# dashboard
# ======================================================================
@frappe.whitelist()
def get_dashboard_stats(warehouse=None):
	"""What a location manager needs to know at a glance.

	Not "how many documents are open" — that is ERPNext's job. This is about whether
	the warehouse is actually put away, whether the ledger can still be trusted, and
	which locations are doing the work.
	"""
	_require_access()
	scope = _scope(warehouse)
	cond, vals = _wh_cond(scope, "b.warehouse")
	lcond, lvals = _wh_cond(scope, "warehouse")

	# --- put-away coverage, in items and in units -------------------------------
	rows = frappe.db.sql(
		"""
		select b.item_code,
			sum(b.actual_qty) as on_hand,
			ifnull(sum(ls.assigned), 0) as shelved
		from `tabBin` b
		left join (
			select warehouse, item_code, sum(qty) as assigned
			from `tabLocation Stock` group by warehouse, item_code
		) ls on ls.warehouse = b.warehouse and ls.item_code = b.item_code
		where b.actual_qty > 0 {cond}
		group by b.item_code
		""".format(cond=cond),
		vals,
		as_dict=True,
	)
	shelved_items = partial_items = loose_items = 0
	units_shelved = units_loose = 0.0
	for r in rows:
		on_hand, shelved = flt(r.on_hand), flt(r.shelved)
		units_shelved += min(shelved, on_hand)
		units_loose += max(on_hand - shelved, 0)
		if shelved <= TOL:
			loose_items += 1
		elif shelved + TOL < on_hand:
			partial_items += 1
		else:
			shelved_items += 1

	# --- the locations themselves ----------------------------------------------
	locs = frappe.get_all(
		"Warehouse Location",
		filters={"is_active": 1, "is_unassigned": 0},
		fields=["name", "warehouse", "location_code", "location_name", "max_qty"],
		limit_page_length=0,
	)
	if scope is not None:
		locs = [l for l in locs if l.warehouse in scope]

	held = {}
	for r in frappe.db.sql(
		"select location, sum(qty) q, count(distinct item_code) n from `tabLocation Stock` "
		"where qty > 0 group by location", as_dict=True
	):
		held[r.location] = {"qty": flt(r.q), "items": cint(r.n)}

	busiest, over_capacity, empty = [], 0, 0
	for l in locs:
		h = held.get(l.name) or {"qty": 0.0, "items": 0}
		if h["qty"] <= TOL:
			empty += 1
		if flt(l.max_qty) and h["qty"] > flt(l.max_qty) + TOL:
			over_capacity += 1
		busiest.append(
			{
				"location": l.name,
				"label": l.location_code or l.name,
				"warehouse": l.warehouse,
				"qty": h["qty"],
				"items": h["items"],
				"max_qty": flt(l.max_qty),
				"fill": (h["qty"] / flt(l.max_qty) * 100) if flt(l.max_qty) else None,
			}
		)
	busiest.sort(key=lambda x: -x["qty"])

	# --- movement, last 7 days --------------------------------------------------
	mcond, mvals = _wh_cond(scope, "m.warehouse")
	recent = frappe.db.sql(
		"""
		select m.entry_type, count(*) as n
		from `tabLocation Stock Movement` m
		where m.docstatus = 1 and m.posting_date >= date_sub(curdate(), interval 7 day) {cond}
		group by m.entry_type
		""".format(cond=mcond),
		mvals,
		as_dict=True,
	)
	moves = {r.entry_type: cint(r.n) for r in recent}

	active = frappe.db.sql(
		"""
		select coalesce(i.source_location, i.target_location) as location, count(*) as n
		from `tabLocation Stock Movement Item` i
		inner join `tabLocation Stock Movement` m on m.name = i.parent
		where m.docstatus = 1 and m.posting_date >= date_sub(curdate(), interval 7 day) {cond}
		group by location order by n desc limit 5
		""".format(cond=mcond),
		mvals,
		as_dict=True,
	)

	# --- items with stock but nowhere declared to keep them ----------------------
	homeless = 0
	if rows:
		dcond, dvals = _wh_cond(scope, "warehouse")
		declared = {
			d[0]
			for d in frappe.db.sql(
				"select distinct parent from `tabItem Default Location` "
				"where parenttype = 'Item' {0}".format(dcond),
				dvals,
			)
		}
		homeless = len([r for r in rows if r.item_code not in declared])

	total_units = units_shelved + units_loose
	return {
		"items_total": len(rows),
		"items_shelved": shelved_items,
		"items_partial": partial_items,
		"items_loose": loose_items,
		"units_shelved": units_shelved,
		"units_loose": units_loose,
		"coverage": (units_shelved / total_units * 100) if total_units else 0,
		"locations": len(locs),
		"locations_empty": empty,
		"locations_over": over_capacity,
		"busiest": busiest[:5],
		"moves_7d": sum(moves.values()),
		"moves_by_type": moves,
		"active_locations": [
			{"location": a.location, "moves": cint(a.n)} for a in active if a.location
		],
		"homeless_items": homeless,
	}


def _count_locations(scope):
	"""Real locations only — the per-warehouse Unassigned Stock location is plumbing."""
	rows = frappe.get_all(
		"Warehouse Location",
		filters={"is_active": 1, "is_unassigned": 0},
		fields=["name", "warehouse"],
	)
	if scope is not None:
		rows = [r for r in rows if r.warehouse in scope]
	return len(rows)


@frappe.whitelist()
def get_unassigned(warehouse=None, search=None, start=0, limit=60, counts_only=0):
	"""Everything in the warehouse that has not been put away on a shelf yet.

	Derived from `Bin.actual_qty` minus what the real locations hold, so it needs no
	seeding and can never drift. Paged, because a single shop can easily have several
	hundred items still loose.

	`counts_only` skips the rows entirely. The dock's bar shows a count and a total
	whether or not anyone opens it, and fetching forty rows with their names to render
	one number is most of what made it feel slow.
	"""
	_require_access()
	scope = _scope(warehouse)
	# `warehouse` alone would be ambiguous between the bin and the balances subquery
	cond, params = _wh_cond(scope, "b.warehouse")
	start, limit = cint(start), cint(limit) or 60

	like_clause, like_params = "", []
	if search:
		like = "%{0}%".format(search.strip())
		like_clause = " and (b.item_code like %s or i.item_name like %s)"
		like_params = [like, like]

	body = """
		from `tabBin` b
		{item_join}
		left join (
			select warehouse, item_code, sum(qty) as assigned
			from `tabLocation Stock` group by warehouse, item_code
		) ss on ss.warehouse = b.warehouse and ss.item_code = b.item_code
		where b.actual_qty - ifnull(ss.assigned, 0) > 0.000001 {cond} {like}
	""".format(
		cond=cond,
		like=like_clause,
		# joining Item is only worth it when its columns are actually selected
		item_join="inner join `tabItem` i on i.name = b.item_code"
		if (search or not cint(counts_only)) else "",
	)

	totals = frappe.db.sql(
		"""select count(*) as items, sum(b.actual_qty - ifnull(ss.assigned, 0)) as qty
		{body}""".format(body=body),
		params + like_params,
		as_dict=True,
	)
	total = totals[0] if totals else {}

	if cint(counts_only):
		return {
			"items": [],
			"start": 0,
			"has_more": cint(total.get("items")) > 0,
			"total_items": cint(total.get("items")),
			"total_qty": flt(total.get("qty")),
			"scope_label": warehouse or _("all warehouses"),
			"counts_only": 1,
		}

	rows = frappe.db.sql(
		"""select b.warehouse, b.item_code, i.item_name, i.stock_uom,
			b.actual_qty - ifnull(ss.assigned, 0) as qty
		{body}
		order by qty desc, b.item_code asc
		limit {limit} offset {start}""".format(body=body, limit=limit + 1, start=start),
		params + like_params,
		as_dict=True,
	)
	has_more = len(rows) > limit
	rows = rows[:limit]

	return {
		"items": rows,
		"start": start,
		"has_more": has_more,
		"total_items": cint(total.get("items")),
		"total_qty": flt(total.get("qty")),
		"scope_label": warehouse or _("all warehouses"),
	}


# ======================================================================
# direct location management
# ======================================================================
# Moving stock between two locations of the same warehouse changes nothing about the
# warehouse's real stock — it is a re-shelving, not a transaction. So it needs no Stock
# Entry and no accounting: a Location Stock Movement records it and that is all.
@frappe.whitelist()
def move_between_locations(warehouse, item_code, from_location, to_location, qty):
	"""Move an item from one shelf to another. Either end may be unassigned stock."""
	_require_preparer()
	qty = flt(qty)
	if qty <= 0:
		frappe.throw(_("Enter a quantity greater than zero."))
	if from_location == to_location:
		frappe.throw(_("Pick a different location to move to."))

	unassigned = frappe.db.get_value(
		"Warehouse Location", {"warehouse": warehouse, "is_unassigned": 1}, "name"
	)
	from_location = from_location or unassigned
	to_location = to_location or unassigned

	entry_type = "Transfer"
	if from_location == unassigned:
		entry_type = "Stock In"
	elif to_location == unassigned:
		entry_type = "Stock Out"

	doc = frappe.get_doc(
		{
			"doctype": "Location Stock Movement",
			"entry_type": entry_type,
			"warehouse": warehouse,
			"posting_date": frappe.utils.nowdate(),
			"remarks": _("Moved on the warehouse board"),
			"items": [
				{
					"item_code": item_code,
					"qty": qty,
					"source_location": from_location,
					"target_location": to_location,
				}
			],
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return {"movement": doc.name, "entry_type": entry_type}


@frappe.whitelist()
def set_location_qty(warehouse, item_code, location, qty):
	"""Set what a shelf holds. The difference comes from, or goes to, unassigned stock.

	Lowering a shelf does not destroy stock — it just stops claiming it, and the
	remainder shows up as unassigned again. Raising it takes from the unassigned pool,
	which is what stops a shelf from claiming more than the warehouse has.
	"""
	_require_preparer()
	from isoft_warehouse_location_management.isoft_location_manager.doctype.location_stock.location_stock import (
		get_balance,
		unassigned_qty,
	)

	if frappe.db.get_value("Warehouse Location", location, "is_unassigned"):
		frappe.throw(
			_("Unassigned stock is whatever is left over — put items on a shelf to change it.")
		)

	target = flt(qty)
	if target < 0:
		frappe.throw(_("A location cannot hold less than nothing."))

	current = get_balance(location, item_code)
	delta = target - current
	if abs(delta) <= TOL:
		return {"changed": 0, "qty": current}

	if delta > 0:
		loose = unassigned_qty(warehouse, item_code)
		if delta > loose + TOL:
			frappe.throw(
				_(
					"Only {0} of {1} is unassigned in {2}. Take the rest off another location first."
				).format(flt(loose), item_code, warehouse),
				title=_("Not Enough Unassigned"),
			)

	result = move_between_locations(
		warehouse,
		item_code,
		from_location=None if delta > 0 else location,
		to_location=location if delta > 0 else None,
		qty=abs(delta),
	)
	result.update({"changed": delta, "qty": target})
	return result


# ======================================================================
# location ledger
# ======================================================================
@frappe.whitelist()
def get_ledger(warehouse=None, location=None, item_code=None, start=0, limit=100):
	"""Every movement that touched a location, newest first.

	One document line becomes one ledger line per end it names, so a transfer reads as
	an out on the shelf it left and an in on the shelf it reached. That is what makes
	the ledger readable per location rather than per document.
	"""
	_require_access()
	scope = _scope(warehouse)
	cond, params = _wh_cond(scope, "m.warehouse")
	start, limit = cint(start), cint(limit) or 100

	extra, extra_params = "", []
	if location:
		extra += " and (i.source_location = %s or i.target_location = %s)"
		extra_params += [location, location]
	if item_code:
		extra += " and i.item_code = %s"
		extra_params.append(item_code)

	rows = frappe.db.sql(
		"""
		select m.name, m.entry_type, m.warehouse, m.posting_date, m.posting_time,
			m.remarks, m.reference_stock_entry, m.reference_sales_document,
			m.reference_doctype, m.owner, m.creation,
			i.item_code, i.item_name, i.qty, i.source_location, i.target_location
		from `tabLocation Stock Movement Item` i
		inner join `tabLocation Stock Movement` m on m.name = i.parent
		where m.docstatus = 1 {cond} {extra}
		order by m.posting_date desc, m.creation desc, i.idx asc
		limit {limit} offset {start}
		""".format(cond=cond, extra=extra, limit=limit + 1, start=start),
		params + extra_params,
		as_dict=True,
	)
	has_more = len(rows) > limit
	rows = rows[:limit]

	unassigned = _unassigned_names()
	out = []
	for r in rows:
		out.append(
			{
				"movement": r.name,
				"entry_type": r.entry_type,
				"warehouse": r.warehouse,
				"posting_date": str(r.posting_date or ""),
				"posting_time": str(r.posting_time or "")[:5],
				"item_code": r.item_code,
				"item_name": r.item_name,
				"qty": flt(r.qty),
				"source": r.source_location,
				"target": r.target_location,
				"source_loose": 1 if r.source_location in unassigned else 0,
				"target_loose": 1 if r.target_location in unassigned else 0,
				"reference": _ledger_reference(r),
				"user": r.owner,
				"remarks": r.remarks,
				# when one location is in focus, say whether this line added or removed
				"direction": (
					"in" if location and r.target_location == location
					else ("out" if location and r.source_location == location else None)
				),
			}
		)
	return {"rows": out, "start": start, "has_more": has_more}


def _unassigned_names():
	return set(frappe.get_all("Warehouse Location", filters={"is_unassigned": 1}, pluck="name"))


def _ledger_reference(row):
	"""What caused the movement, named as the document that caused it."""
	if row.reference_stock_entry:
		return {"doctype": "Stock Entry", "name": row.reference_stock_entry}
	if row.reference_sales_document:
		return {"doctype": row.reference_doctype or "Sales Invoice", "name": row.reference_sales_document}
	return None


@frappe.whitelist()
def get_ledger_locations(warehouse=None):
	"""Locations available to filter the ledger by, within the current scope."""
	_require_access()
	scope = _scope(warehouse)
	rows = frappe.get_all(
		"Warehouse Location",
		filters={"is_active": 1},
		fields=["name", "location_code", "location_name", "warehouse", "is_unassigned"],
		order_by="warehouse asc, is_unassigned asc, pick_priority asc, location_code asc",
	)
	if scope is not None:
		rows = [r for r in rows if r.warehouse in scope]
	return rows


# ======================================================================
# what one location holds
# ======================================================================
@frappe.whitelist()
def get_location_contents(location):
	"""Everything on one shelf, for the editor behind its Edit button."""
	_require_access()
	from isoft_warehouse_location_management.isoft_location_manager.doctype.location_stock.location_stock import (
		unassigned_qty,
	)

	loc = frappe.db.get_value(
		"Warehouse Location",
		location,
		["name", "location_code", "location_name", "warehouse", "description",
		 "is_active", "is_unassigned", "location_type", "max_qty", "zone"],
		as_dict=True,
	)
	if not loc:
		frappe.throw(_("Location {0} does not exist.").format(location))

	if loc.is_unassigned:
		# the loose pool is derived; the dock is where it is managed
		return {"location": loc, "items": [], "total_qty": 0, "is_unassigned": 1}

	rows = frappe.get_all(
		"Location Stock",
		filters={"location": location},
		fields=["item_code", "item_name", "qty"],
		order_by="qty desc, item_code asc",
		limit_page_length=0,
	)
	defaults = _item_defaults(loc.warehouse, [r.item_code for r in rows])
	items = []
	for r in rows:
		held = flt(r.qty)
		mine = defaults.get(r.item_code) or {}
		items.append(
			{
				"item_code": r.item_code,
				"item_name": r.item_name,
				"qty": held,
				"uom": frappe.db.get_value("Item", r.item_code, "stock_uom"),
				# how much more this shelf could take without breaking the partition
				"loose": unassigned_qty(loc.warehouse, r.item_code),
				# where this item says it is picked from. There is no put-away equivalent:
				# putting away is decided at the shelf, not declared in advance.
				"default_out": 1 if mine.get("out") == location else 0,
				"out_elsewhere": mine.get("out") if mine.get("out") and mine.get("out") != location else None,
			}
		)

	return {
		"location": loc,
		"items": items,
		"total_qty": sum(i["qty"] for i in items),
		"is_unassigned": 0,
	}


def _item_defaults(warehouse, item_codes):
	"""{item_code: {"out": location}} for one warehouse."""
	out = {}
	if not item_codes:
		return out
	for r in frappe.get_all(
		"Item Default Location",
		filters={"parent": ["in", list(set(item_codes))], "parenttype": "Item", "warehouse": warehouse},
		fields=["parent", "location", "default_out"],
		limit_page_length=0,
	):
		if r.default_out:
			out.setdefault(r.parent, {})["out"] = r.location
	return out


@frappe.whitelist()
def set_item_default_location(item_code, warehouse, location, direction="out", on=1):
	"""Say where an item is picked from in this warehouse.

	Only picking has a declared location. Where something is *put away* is a decision
	made at the shelf, by whoever is holding it — so it is chosen on the document each
	time rather than set in advance.

	One location holds the role per warehouse, so setting it here clears it wherever it
	was before.
	"""
	_require_preparer()
	if direction != "out":
		frappe.throw(_("Only a pick location can be declared."))
	field = "default_out"
	on = cint(on)

	if frappe.db.get_value("Warehouse Location", location, "is_unassigned"):
		frappe.throw(_("Unassigned stock is where things are before they have a home."))

	item = frappe.get_doc("Item", item_code)
	rows = [r for r in (item.get("custom_default_locations") or []) if r.warehouse == warehouse]

	# the role belongs to one location at a time
	for r in rows:
		if r.location != location:
			r.set(field, 0)

	mine = next((r for r in rows if r.location == location), None)
	if on:
		if not mine:
			mine = item.append("custom_default_locations", {"warehouse": warehouse, "location": location})
			mine.set("default_out", 0)
		mine.set(field, 1)
	elif mine:
		mine.set(field, 0)

	# a row that claims nothing is just noise
	item.set(
		"custom_default_locations",
		[r for r in (item.get("custom_default_locations") or []) if cint(r.default_out)],
	)
	item.flags.ignore_permissions = True
	item.flags.ignore_mandatory = True
	item.save(ignore_permissions=True)

	from isoft_warehouse_location_management.isoft_location_manager.api import log_activity

	log_activity(
		"Location", "Default {0}".format("put-away" if direction == "in" else "pick"),
		location, warehouse=warehouse, reference_type="Warehouse Location",
		message=_("{0} · {1}").format(item_code, _("set") if on else _("cleared")),
	)
	return _item_defaults(warehouse, [item_code]).get(item_code) or {}


@frappe.whitelist()
def apply_location_contents(location, rows):
	"""Set what a shelf holds, item by item, in one round trip.

	Every change goes through the same re-shelving the board uses: lowering a line
	returns the difference to unassigned stock, raising it takes from there. Nothing
	here can invent or destroy stock — it only moves it inside the warehouse.
	"""
	_require_preparer()
	loc = frappe.db.get_value(
		"Warehouse Location", location, ["warehouse", "is_unassigned"], as_dict=True
	)
	if not loc:
		frappe.throw(_("Location {0} does not exist.").format(location))
	if loc.is_unassigned:
		frappe.throw(_("Unassigned stock is whatever is left over — it cannot be edited directly."))

	applied, problems = [], []
	for row in frappe.parse_json(rows) or []:
		item_code = row.get("item_code")
		if not item_code:
			continue
		try:
			result = set_location_qty(loc.warehouse, item_code, location, flt(row.get("qty")))
			if result.get("changed"):
				applied.append({"item_code": item_code, "changed": flt(result["changed"])})
		except frappe.ValidationError as e:
			problems.append({"item_code": item_code, "message": str(e)})

	return {"applied": applied, "problems": problems}


# ======================================================================
# reconciliation
# ======================================================================
@frappe.whitelist()
def get_drift(warehouse=None, limit=200):
	"""Items whose locations claim more than the warehouse actually holds.

	The partition should always balance. It stops balancing when stock leaves through
	a document the app does not mirror — so this is the number that says whether the
	ledger can still be trusted, per item.
	"""
	_require_access()
	scope = _scope(warehouse)
	cond, params = _wh_cond(scope, "ss.warehouse")
	rows = frappe.db.sql(
		"""
		select ss.warehouse, ss.item_code, i.item_name,
			sum(ss.qty) as assigned,
			ifnull(b.actual_qty, 0) as bin_qty,
			ifnull(b.actual_qty, 0) - sum(ss.qty) as unassigned
		from `tabLocation Stock` ss
		inner join `tabItem` i on i.name = ss.item_code
		left join `tabBin` b on b.item_code = ss.item_code and b.warehouse = ss.warehouse
		where 1 = 1 {cond}
		group by ss.warehouse, ss.item_code, i.item_name, b.actual_qty
		having sum(ss.qty) > ifnull(b.actual_qty, 0) + 0.000001
		order by (sum(ss.qty) - ifnull(b.actual_qty, 0)) desc
		limit {limit}
		""".format(cond=cond, limit=cint(limit) or 200),
		params,
		as_dict=True,
	)
	for r in rows:
		r["over_claimed"] = flt(r.assigned) - flt(r.bin_qty)
	return rows


@frappe.whitelist()
def clear_drift(warehouse, item_code):
	"""Write a location balance back down to what the warehouse really holds.

	Posts a real Stock Out movement so the correction is on the record rather than an
	invisible edit, taking it off the fullest locations first.
	"""
	_require_preparer()
	rows = frappe.get_all(
		"Location Stock",
		filters={"warehouse": warehouse, "item_code": item_code, "qty": [">", 0]},
		fields=["location", "qty"],
		order_by="qty desc",
	)
	assigned = sum(flt(r.qty) for r in rows)
	bin_qty = flt(
		frappe.db.get_value("Bin", {"warehouse": warehouse, "item_code": item_code}, "actual_qty")
	)
	excess = assigned - bin_qty
	if excess <= TOL:
		return {"corrected": 0}

	items, left = [], excess
	for r in rows:
		if left <= TOL:
			break
		take = min(left, flt(r.qty))
		items.append({"item_code": item_code, "qty": take, "source_location": r.location})
		left -= take

	doc = frappe.get_doc(
		{
			"doctype": "Location Stock Movement",
			"entry_type": "Stock Out",
			"warehouse": warehouse,
			"posting_date": frappe.utils.nowdate(),
			"remarks": _(
				"Correction: locations claimed {0} but the warehouse holds {1}."
			).format(assigned, bin_qty),
			"items": items,
		}
	)
	doc.flags.ignore_permissions = True
	doc.flags.picking_validation_mode = "Warn"
	doc.insert(ignore_permissions=True)
	doc.submit()
	return {"corrected": excess, "movement": doc.name}


# ======================================================================
# warehouse explorer
# ======================================================================
@frappe.whitelist()
def get_locations_with_items(warehouse=None, search=None):
	_require_access()
	scope = _scope(warehouse)
	search = (search or "").strip().lower()

	locations = frappe.get_all(
		"Warehouse Location",
		filters={"is_active": 1},
		fields=[
			"name", "location_code", "location_name", "warehouse", "description",
			"is_active", "is_unassigned", "location_type", "pick_priority", "zone",
			"max_qty",
		],
		order_by="warehouse asc, is_unassigned asc, pick_priority asc, location_code asc",
	)
	if scope is not None:
		locations = [s for s in locations if s.warehouse in scope]

	stock = frappe.get_all(
		"Location Stock",
		fields=["location", "item_code", "item_name", "qty", "warehouse"],
		limit_page_length=0,
	)
	if scope is not None:
		stock = [r for r in stock if r.warehouse in scope]

	by_section = {}
	for r in stock:
		by_section.setdefault(r.location, []).append(r)

	# zones are an organising layer over the same locations — one lookup, not one per card
	zone_meta = {
		z.name: z
		for z in frappe.get_all(
			"Warehouse Zone",
			fields=["name", "zone_code", "zone_name", "warehouse", "sequence"],
			limit_page_length=0,
		)
	}

	result = []
	for s in locations:
		if s.is_unassigned:
			# shown in its own dock, which can page and search — a capped column could
			# never do justice to several hundred loose items
			continue
		items = by_section.get(s.name, [])
		if search:
			sec_match = search in (s.location_code or "").lower() or search in (s.location_name or "").lower()
			items = [
				i for i in items
				if search in (i.item_code or "").lower() or search in (i.item_name or "").lower()
			] if not sec_match else items
			if not sec_match and not items:
				continue
		items.sort(key=lambda i: (i.item_code or ""))
		result.append(
			{
				"location": s.name,
				"location_code": s.location_code,
				"location_name": s.location_name,
				"warehouse": s.warehouse,
				"description": s.description,
				"is_active": s.is_active,
				"is_unassigned": 0,
				"location_type": s.location_type,
				"max_qty": flt(s.max_qty),
				"zone": s.zone,
				"zone_code": (zone_meta.get(s.zone) or {}).get("zone_code"),
				"zone_name": (zone_meta.get(s.zone) or {}).get("zone_name"),
				"zone_seq": cint((zone_meta.get(s.zone) or {}).get("sequence")),
				"items": items,
				"item_count": len(items),
				"listed": len(items),
				"total_qty": sum(flt(i.qty) for i in items),
			}
		)
	return result


UNASSIGNED_PREVIEW = 60


def _unassigned_location_row(location, search=None):
	"""What is in the warehouse but not yet put away.

	Derived on the fly from `Bin.actual_qty` minus what the real locations hold, so it
	needs no seeding and can never drift. Only the largest holdings are listed — the
	count tells the operator how much more there is.
	"""
	like = "%{0}%".format(search) if search else None
	params = [location.warehouse]
	clause = ""
	if like:
		clause = " and (b.item_code like %s or i.item_name like %s)"
		params += [like, like]

	rows = frappe.db.sql(
		"""
		select b.item_code, i.item_name,
			b.actual_qty - ifnull(ss.assigned, 0) as qty
		from `tabBin` b
		inner join `tabItem` i on i.name = b.item_code
		left join (
			select warehouse, item_code, sum(qty) as assigned
			from `tabLocation Stock` group by warehouse, item_code
		) ss on ss.warehouse = b.warehouse and ss.item_code = b.item_code
		where b.warehouse = %s and b.actual_qty - ifnull(ss.assigned, 0) > 0.000001
		{0}
		order by qty desc
		""".format(clause),
		params,
		as_dict=True,
	)
	if search and not rows:
		sec_match = search in (location.location_code or "").lower() or search in (
			location.location_name or ""
		).lower()
		if not sec_match:
			return None

	preview = rows[:UNASSIGNED_PREVIEW]
	for r in preview:
		r["warehouse"] = location.warehouse
		r["location"] = location.name

	return {
		"location": location.name,
		"location_code": location.location_code,
		"location_name": location.location_name,
		"warehouse": location.warehouse,
		"description": location.description,
		"is_active": 1,
		"is_unassigned": 1,
		"items": preview,
		"item_count": len(rows),
		"listed": len(preview),
		"total_qty": sum(flt(r.qty) for r in rows),
	}


@frappe.whitelist()
def get_locations_for_warehouse(warehouse):
	"""Active locations belonging to a specific warehouse (for pickers)."""
	_require_access()
	return frappe.get_all(
		"Warehouse Location",
		filters={"is_active": 1, "warehouse": warehouse},
		fields=["name", "location_code", "location_name", "is_unassigned", "location_type", "pick_priority"],
		order_by="is_unassigned asc, pick_priority asc, location_code asc",
	)


@frappe.whitelist()
def get_pick_options(warehouse, items, qty_by_item=None):
	"""Where each item can be picked from, and which location should already be chosen.

	Thin wrapper over the shared resolver so the dashboard, the desk forms and the
	Stock Entry hook all answer the question the same way.
	Returns {item_code: {mode, location, candidates, split, reason}}.
	"""
	_require_access()
	from isoft_warehouse_location_management.isoft_location_manager.location_resolver import resolve

	return resolve(warehouse, items, "out", qty_by_item)


@frappe.whitelist()
def get_putaway_options(warehouse, items):
	"""Where each item should be put away. Same resolver, other direction."""
	_require_access()
	from isoft_warehouse_location_management.isoft_location_manager.location_resolver import resolve

	return resolve(warehouse, items, "in")


# ======================================================================
# manage locations + distribute stock (Location Stock Movement)
# ======================================================================
@frappe.whitelist()
def create_locations(warehouse, rows):
	"""Bulk-create locations in one warehouse. `rows` = JSON list of {location_code, description}.

	The location name is taken from the code (no separate name needed). Existing codes are skipped.
	"""
	_require_access()
	if not warehouse:
		frappe.throw(_("Select a warehouse."))
	rows = frappe.parse_json(rows)
	created, skipped = [], []
	for r in rows:
		code = (r.get("location_code") or "").strip().upper()
		if not code:
			continue
		# codes are unique per warehouse now, so the same rack label may exist elsewhere
		if frappe.db.exists("Warehouse Location", {"warehouse": warehouse, "location_code": code}):
			skipped.append(code)
			continue
		if code == UNASSIGNED_CODE:
			skipped.append(code)
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Warehouse Location",
				"location_code": code,
				"location_name": code,
				"warehouse": warehouse,
				"description": r.get("description") or None,
				"is_active": 1,
			}
		)
		doc.insert(ignore_permissions=True)
		created.append(doc.name)
	if created:
		from isoft_warehouse_location_management.isoft_location_manager.api import log_activity

		log_activity("Location", "Created", ", ".join(created[:8]) + ("…" if len(created) > 8 else ""),
			warehouse=warehouse, reference_type="Warehouse Location",
			message=_("{0} location(s): {1}").format(len(created), ", ".join(created)))
	return {"created": len(created), "names": created, "skipped": skipped}


@frappe.whitelist()
def update_location(name, location_name=None, description=None, is_active=None):
	_require_access()
	doc = frappe.get_doc("Warehouse Location", name)
	if location_name is not None:
		doc.location_name = location_name
	if description is not None:
		doc.description = description
	if is_active is not None:
		doc.is_active = cint(is_active)
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	from isoft_warehouse_location_management.isoft_location_manager.api import log_activity

	log_activity("Location", "Updated", doc.name, warehouse=doc.warehouse, reference_type="Warehouse Location",
		message=_("Active") if doc.is_active else _("Deactivated"))
	return doc.name


@frappe.whitelist()
def create_movement(entry_type, warehouse, items, posting_date=None, remarks=None):
	"""Create & submit a Location Stock Movement (the In/Out document) from the UI.

	`items` is a JSON list of {item_code, qty, source_location, target_location}.
	All location-balance rules and the real-stock (Bin) cap are enforced by the
	Location Stock Movement controller; no GL / Stock Ledger Entry is ever posted.
	"""
	_require_access()
	rows = frappe.parse_json(items)
	clean = []
	for r in rows:
		if not r.get("item_code") or flt(r.get("qty")) <= 0:
			continue
		clean.append(
			{
				"item_code": r.get("item_code"),
				"qty": flt(r.get("qty")),
				"source_location": r.get("source_location") or None,
				"target_location": r.get("target_location") or None,
			}
		)
	if not clean:
		frappe.throw(_("Add at least one item with a quantity."))
	doc = frappe.get_doc(
		{
			"doctype": "Location Stock Movement",
			"entry_type": entry_type,
			"warehouse": warehouse,
			"posting_date": posting_date or frappe.utils.nowdate(),
			"remarks": remarks,
			"items": clean,
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


@frappe.whitelist()
def create_stock_entry(entry_type, items, source_warehouse=None, target_warehouse=None, posting_date=None):
	"""Create & submit a real ERPNext Stock Entry on behalf of a Location Manager.

	Costs are not exposed: receipts fall back to the item's valuation (or zero-valuation
	allowed); issues/transfers use existing stock valuation. Serial numbers are passed
	through when the item requires them. Location picks feed the Stock Entry hook, which
	mirrors them into cost-free Location Stock Movements.
	"""
	import re

	from isoft_warehouse_location_management.isoft_location_manager.api import is_warehouse_enabled, log_activity

	if not ({"Location Manager", "System Manager"} & _roles()):
		frappe.throw(_("Only a Location Manager can create stock transactions."), frappe.PermissionError)
	if entry_type not in ("Material Receipt", "Material Issue", "Material Transfer"):
		frappe.throw(_("Invalid transaction type."))

	for wh in (source_warehouse, target_warehouse):
		if wh and not is_warehouse_enabled(wh):
			frappe.throw(_("Warehouse {0} is not enabled for Isoft Location Manager.").format(wh))
	if entry_type in ("Material Issue", "Material Transfer") and not source_warehouse:
		frappe.throw(_("Select a source warehouse."))
	if entry_type in ("Material Receipt", "Material Transfer") and not target_warehouse:
		frappe.throw(_("Select a target warehouse."))

	rows = frappe.parse_json(items)
	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = entry_type
	company_wh = target_warehouse or source_warehouse
	se.company = frappe.db.get_value("Warehouse", company_wh, "company") or frappe.defaults.get_user_default("Company")
	if posting_date:
		se.set_posting_time = 1
		se.posting_date = posting_date

	# Difference (stock adjustment) account is needed for Receipt/Issue value offset.
	diff_account = None
	if entry_type in ("Material Receipt", "Material Issue"):
		diff_account = (
			frappe.get_cached_value("Company", se.company, "stock_adjustment_account")
			or frappe.db.get_value("Account", {"company": se.company, "account_type": "Stock Adjustment", "is_group": 0}, "name")
			or frappe.db.get_value("Account", {"company": se.company, "account_type": "Temporary", "is_group": 0}, "name")
		)
		if not diff_account:
			frappe.throw(_("Set a default Stock Adjustment Account for company {0} to post receipts/issues.").format(se.company))

	for r in rows:
		item = r.get("item_code")
		qty = flt(r.get("qty"))
		if not item or qty <= 0:
			continue
		serial = r.get("serial_no") or ""
		serial = "\n".join([s for s in re.split(r"[\s,]+", serial) if s]) or None
		stock_uom = frappe.db.get_value("Item", item, "stock_uom")
		line = {"item_code": item, "qty": qty, "serial_no": serial,
			"uom": stock_uom, "stock_uom": stock_uom, "conversion_factor": 1}
		if entry_type == "Material Receipt":
			line["t_warehouse"] = target_warehouse
			line["custom_to_location"] = r.get("to_location") or None
			line["expense_account"] = diff_account
			val = flt(frappe.db.get_value("Item", item, "valuation_rate"))
			if val:
				line["basic_rate"] = val
			else:
				line["allow_zero_valuation_rate"] = 1
		elif entry_type == "Material Issue":
			line["s_warehouse"] = source_warehouse
			line["custom_from_location"] = r.get("from_location") or None
			line["expense_account"] = diff_account
		else:  # Material Transfer
			line["s_warehouse"] = source_warehouse
			line["t_warehouse"] = target_warehouse
			line["custom_from_location"] = r.get("from_location") or None
			line["custom_to_location"] = r.get("to_location") or None
		se.append("items", line)

	if not se.items:
		frappe.throw(_("Add at least one item with a quantity."))

	se.flags.ignore_permissions = True
	se.insert(ignore_permissions=True)
	se.submit()
	log_activity("Movement", "Stock Entry (" + entry_type + ")", se.name, warehouse=company_wh,
		reference_type="Stock Entry", message=_("{0} item line(s)").format(len(se.items)))
	return se.name


@frappe.whitelist()
def get_available_serials(item_code, warehouse, search=None):
	"""Serial numbers of an item currently in a warehouse (for issue/transfer picking)."""
	_require_access()
	if not item_code or not warehouse:
		return []
	filters = {"item_code": item_code, "warehouse": warehouse}
	if search:
		filters["name"] = ["like", f"%{search}%"]
	return frappe.get_all("Serial No", filters=filters, pluck="name", order_by="name asc", limit_page_length=100)


@frappe.whitelist()
def get_movements(warehouse=None, limit=60):
	_require_access()
	scope = _scope(warehouse)
	rows = frappe.get_all(
		"Location Stock Movement",
		filters={"docstatus": ["<", 2]},
		fields=["name", "entry_type", "warehouse", "posting_date", "docstatus", "remarks"],
		order_by="creation desc",
		limit_page_length=int(limit),
	)
	if scope is not None:
		rows = [r for r in rows if r.warehouse in scope]
	return rows


@frappe.whitelist()
def get_logs(category=None, user=None, search=None, warehouse=None, limit=200):
	"""Audit trail for requests / locations / movements, newest first."""
	_require_access()
	scope = _scope(warehouse)
	filters = {}
	if category and category != "all":
		filters["category"] = category
	if user:
		filters["user"] = user
	rows = frappe.get_all(
		"Picking Log",
		filters=filters,
		fields=["activity_datetime", "user", "category", "action", "reference_name", "warehouse", "message"],
		order_by="activity_datetime desc",
		limit_page_length=int(limit),
	)
	if scope is not None:
		rows = [r for r in rows if (not r.warehouse) or r.warehouse in scope]
	if search:
		s = search.lower()
		rows = [
			r for r in rows
			if s in (r.reference_name or "").lower() or s in (r.message or "").lower() or s in (r.user or "").lower()
		]
	return rows


@frappe.whitelist()
def get_log_users():
	"""Distinct users that appear in the log (for the filter dropdown)."""
	_require_access()
	return [r.user for r in frappe.get_all("Picking Log", fields=["user"], group_by="user", order_by="user asc") if r.user]


# ======================================================================
# requests manager
# ======================================================================
_BUCKET = {
	"open": ["Requested"],
	"in_progress": ["In Progress"],
	"closed": ["Prepared", "Cancelled"],
}


# The switches that change how the module behaves. Every one is global — on or off for
# the whole site — because a rule that holds for some items or some locations and not
# others is a rule nobody can state, let alone rely on.
SWITCHES = (
	"enabled",
	"enable_stock_entry",
	"enable_delivery_note",
	"enable_pos",
	"enable_purchase",
	"auto_resolve_locations",
	"allow_location_on_in",
	"allow_pick_from_unassigned",
	"require_location_on_out",
)


@frappe.whitelist()
def get_settings():
	_require_admin()
	from isoft_warehouse_location_management.isoft_location_manager.api import setting

	out = {
		"theme_color": doc_theme(),
		"stock_validation": frappe.db.get_single_value("Picking Settings", "stock_validation") or "Block",
		"default_warehouse": frappe.db.get_single_value("Picking Settings", "default_warehouse"),
		"enabled_warehouses": [
			r.warehouse for r in frappe.get_single("Picking Settings").enabled_warehouses
		],
	}
	# read through `setting`, so a switch that has never been saved reports its documented
	# default rather than the 0 a missing Check row would otherwise look like
	for name in SWITCHES:
		out[name] = 1 if setting(name) else 0
	return out


def doc_theme():
	return frappe.db.get_single_value("Picking Settings", "theme_color") or "Blue"


@frappe.whitelist()
def save_settings(theme_color=None, stock_validation=None, default_warehouse=None,
		enabled_warehouses=None, switches=None):
	_require_admin()
	doc = frappe.get_single("Picking Settings")
	for name, value in (frappe.parse_json(switches) if switches else {}).items():
		if name in SWITCHES:
			doc.set(name, cint(value))
	if theme_color:
		doc.theme_color = theme_color
	if stock_validation:
		doc.stock_validation = stock_validation
	doc.default_warehouse = default_warehouse or None
	if enabled_warehouses is not None:
		doc.enabled_warehouses = []
		for wh in frappe.parse_json(enabled_warehouses):
			if wh:
				doc.append("enabled_warehouses", {"warehouse": wh})
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	return {"ok": True}


# ----------------------------------------------------------------------
# Zones
# ----------------------------------------------------------------------
# A zone groups the locations of one warehouse — an aisle, a cold room, a returns
# corner. Nothing about picking depends on it: stock lives in a location, and a
# warehouse that never creates a zone behaves exactly as it did before.


@frappe.whitelist()
def get_zones(warehouse=None, with_counts=1):
	"""Zones in scope, in display order, optionally with what they hold."""
	_require_access()
	scope = _scope(warehouse)
	filters = {}
	if scope is not None:
		filters["warehouse"] = ["in", list(scope)]
	zones = frappe.get_all(
		"Warehouse Zone",
		filters=filters,
		fields=["name", "zone_code", "zone_name", "warehouse", "sequence", "description", "is_active"],
		order_by="warehouse asc, sequence asc, zone_code asc",
		limit_page_length=0,
	)
	if not cint(with_counts) or not zones:
		return zones

	names = [z.name for z in zones]
	counts = frappe.db.sql(
		"""select zone, count(*) as n from `tabWarehouse Location`
		   where zone in %(names)s and is_active = 1 and ifnull(is_unassigned, 0) = 0
		   group by zone""",
		{"names": names},
		as_dict=True,
	)
	by_zone = {r.zone: cint(r.n) for r in counts}
	for z in zones:
		z["location_count"] = by_zone.get(z.name, 0)
	return zones


@frappe.whitelist()
def save_zone(warehouse, zone_code, zone_name=None, description=None, sequence=0,
		is_active=1, name=None):
	"""Create or rename a zone. The code is the identity; the name is for reading."""
	_require_preparer()
	if warehouse not in (_scope(None) or {warehouse}):
		frappe.throw(_("Warehouse {0} is not in your scope.").format(warehouse))

	if name and frappe.db.exists("Warehouse Zone", name):
		doc = frappe.get_doc("Warehouse Zone", name)
	else:
		doc = frappe.new_doc("Warehouse Zone")
		doc.warehouse = warehouse

	doc.zone_code = (zone_code or "").strip().upper()
	doc.zone_name = (zone_name or "").strip() or doc.zone_code.title()
	doc.description = description
	doc.sequence = cint(sequence)
	doc.is_active = cint(is_active)
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	return {"ok": True, "name": doc.name, "zone_code": doc.zone_code, "zone_name": doc.zone_name}


@frappe.whitelist()
def delete_zone(name):
	"""Remove a zone. Its locations are simply unfiled — no stock moves."""
	_require_preparer()
	if not frappe.db.exists("Warehouse Zone", name):
		return {"ok": True, "unfiled": 0}
	freed = frappe.db.count("Warehouse Location", {"zone": name})
	doc = frappe.get_doc("Warehouse Zone", name)
	doc.flags.ignore_permissions = True
	doc.delete()
	return {"ok": True, "unfiled": freed}


@frappe.whitelist()
def remove_item_from_location(location, item_code):
	"""Take an item off a location entirely.

	Setting a quantity to zero returns the stock but leaves the row behind, which is how
	a location remembers that an item belongs there. Sometimes that memory is the thing
	to get rid of — the item was put on the wrong shelf, or it is not kept there any
	more. This returns whatever is held to unassigned stock and then removes the row, so
	the location stops listing the item at all.

	Nothing is destroyed either way: the goods stay in the warehouse.
	"""
	_require_preparer()
	loc = frappe.db.get_value(
		"Warehouse Location", location, ["name", "warehouse", "is_unassigned"], as_dict=True
	)
	if not loc:
		frappe.throw(_("Location {0} does not exist.").format(location))
	if cint(loc.is_unassigned):
		frappe.throw(
			_("Unassigned stock is whatever is left over — put the item on a location to change it.")
		)
	if loc.warehouse not in (_scope(None) or {loc.warehouse}):
		frappe.throw(_("Warehouse {0} is not in your scope.").format(loc.warehouse))

	row = frappe.db.get_value(
		"Location Stock", {"location": location, "item_code": item_code}, ["name", "qty"], as_dict=True
	)
	if not row:
		return {"ok": True, "returned": 0}

	returned = flt(row.qty)
	if returned > TOL:
		# through the board's own path, so the ledger says where it went
		move_between_locations(loc.warehouse, item_code, location, None, returned)

	# re-read: the movement above zeroes the row rather than removing it
	name = frappe.db.get_value("Location Stock", {"location": location, "item_code": item_code}, "name")
	if name:
		frappe.delete_doc("Location Stock", name, ignore_permissions=True, force=True)

	# it can hardly be the pick location for an item it no longer holds
	if frappe.db.exists("Item Default Location", {"location": location, "parent": item_code}):
		set_item_default_location(item_code, loc.warehouse, location, "out", 0)

	return {"ok": True, "returned": returned}


@frappe.whitelist()
def location_delete_preview(name):
	"""What deleting this location would mean, before anyone confirms it."""
	_require_access()
	loc = frappe.db.get_value(
		"Warehouse Location", name, ["name", "location_code", "warehouse", "is_unassigned"], as_dict=True
	)
	if not loc:
		frappe.throw(_("Location {0} does not exist.").format(name))

	rows = frappe.get_all(
		"Location Stock",
		filters={"location": name, "qty": [">", 0]},
		fields=["item_code", "item_name", "qty"],
		order_by="item_code",
		limit_page_length=0,
	)
	return {
		"location": loc.name,
		"label": loc.location_code or loc.name,
		"warehouse": loc.warehouse,
		"is_unassigned": cint(loc.is_unassigned),
		"items": rows,
		"item_count": len(rows),
		"total_qty": sum(flt(r.qty) for r in rows),
		"declared_for": frappe.db.count("Item Default Location", {"location": name}),
	}


@frappe.whitelist()
def delete_location(name):
	"""Remove a location, returning anything it holds to unassigned stock.

	Nothing is destroyed. The stock stays in the warehouse; it simply stops being
	claimed by a location, which is what unassigned stock *is* — the remainder the
	partition does not account for. So the movement is recorded the same way any other
	re-shelving is, and the totals do not move.
	"""
	_require_preparer()
	loc = frappe.db.get_value(
		"Warehouse Location", name, ["name", "warehouse", "is_unassigned"], as_dict=True
	)
	if not loc:
		frappe.throw(_("Location {0} does not exist.").format(name))
	if cint(loc.is_unassigned):
		frappe.throw(
			_("Unassigned stock is derived, not stored — there is nothing there to delete.")
		)
	if loc.warehouse not in (_scope(None) or {loc.warehouse}):
		frappe.throw(_("Warehouse {0} is not in your scope.").format(loc.warehouse))

	# empty it first, through the same path the board uses, so the ledger shows where
	# the stock went rather than it simply vanishing from a location one day
	emptied = []
	for r in frappe.get_all(
		"Location Stock", filters={"location": name, "qty": [">", 0]},
		fields=["item_code", "qty"], limit_page_length=0,
	):
		move_between_locations(loc.warehouse, r.item_code, name, None, flt(r.qty))
		emptied.append({"item_code": r.item_code, "qty": flt(r.qty)})

	# the zero-balance rows are bookkeeping for a location that is about to stop existing
	for row in frappe.get_all("Location Stock", filters={"location": name}, pluck="name"):
		frappe.delete_doc("Location Stock", row, ignore_permissions=True, force=True)

	# an item that named this as its pick location no longer has one. Cleared through the
	# app's own path so the Item document is saved properly rather than edited underneath
	# it, which would leave a stale child table in the document cache.
	declared = frappe.get_all(
		"Item Default Location",
		filters={"location": name, "parenttype": "Item"},
		fields=["parent"], limit_page_length=0,
	)
	for parent in {r.parent for r in declared}:
		set_item_default_location(parent, loc.warehouse, name, "out", 0)

	# `force` skips only the link check, and the ledger points here on purpose: every
	# movement that ever touched this location names it, including the ones just made
	# emptying it. History is not rewritten when a location is retired — those entries
	# keep the name they were written with, and the ledger still reads correctly.
	# `on_trash` still runs, so the guard against deleting unassigned stock stays live.
	frappe.delete_doc("Warehouse Location", name, force=1, ignore_permissions=True)

	from isoft_warehouse_location_management.isoft_location_manager.api import log_activity

	# "Location" is one of the log's fixed categories; the action carries the detail
	log_activity(
		"Location",
		_("Deleted {0} — {1} item(s) returned to unassigned stock").format(name, len(emptied)),
		warehouse=loc.warehouse,
	)
	return {"ok": True, "returned": emptied}


@frappe.whitelist()
def set_location_zone(locations, zone=None):
	"""File one or more locations under a zone (or unfile them with an empty zone).

	Filing is not a stock movement: the goods do not move, only the way the warehouse
	is described. So this writes the link and nothing else.
	"""
	_require_preparer()
	names = frappe.parse_json(locations) if isinstance(locations, str) else locations
	if isinstance(names, str):
		names = [names]
	names = [n for n in (names or []) if n]
	if not names:
		return {"ok": True, "moved": 0}

	zone_wh = frappe.db.get_value("Warehouse Zone", zone, "warehouse") if zone else None
	if zone and not zone_wh:
		frappe.throw(_("Zone {0} no longer exists.").format(zone))

	moved, problems = 0, []
	for name in names:
		loc = frappe.db.get_value(
			"Warehouse Location", name, ["warehouse", "is_unassigned"], as_dict=True
		)
		if not loc:
			problems.append(_("{0} no longer exists.").format(name))
			continue
		if loc.is_unassigned:
			problems.append(_("{0} is unassigned stock and is not part of any zone.").format(name))
			continue
		if zone and loc.warehouse != zone_wh:
			problems.append(
				_("{0} is in {1}, but that zone belongs to {2}.").format(name, loc.warehouse, zone_wh)
			)
			continue
		frappe.db.set_value("Warehouse Location", name, "zone", zone or None, update_modified=False)
		moved += 1

	return {"ok": not problems, "moved": moved, "problems": problems}


# ----------------------------------------------------------------------
# Import / export
# ----------------------------------------------------------------------
# Thin pass-throughs so the page can reach the transfer module the same way it reaches
# everything else. The work, and every check, lives in transfer.py.


@frappe.whitelist()
def transfer_read(content, filename=None):
	from isoft_warehouse_location_management.isoft_location_manager import transfer

	return transfer.read_upload(content, filename)


@frappe.whitelist()
def transfer_check(sheets):
	from isoft_warehouse_location_management.isoft_location_manager import transfer

	return transfer.check_sheets(sheets)


@frappe.whitelist()
def transfer_apply(sheets):
	from isoft_warehouse_location_management.isoft_location_manager import transfer

	return transfer.apply_sheets(sheets)
