# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt
#
# One resolver, called by every transaction that can carry a location.
#
# It answers a single question: for this item, in this warehouse, moving in this
# direction — which location should already be filled in? Most of the time there is
# exactly one sensible answer, and the operator should never have to pick it.
#
#   locked     one candidate. Fill it in, show a chip, do not ask.
#   suggested  several candidates, one clearly best. Preselect it, keep the rest.
#   choose     several candidates, no clear winner.
#   split      no single location covers the line; propose an allocation.
#   none       nothing holds this item here (outbound only).

import frappe
from frappe import _
from frappe.utils import flt

from isoft_warehouse_location_management.isoft_location_manager.api import is_enabled, setting
from isoft_warehouse_location_management.isoft_location_manager.doctype.location_stock.location_stock import (
	bin_quantities,
	location_balances,
)
from isoft_warehouse_location_management.isoft_location_manager.doctype.warehouse_location.warehouse_location import (
	get_unassigned_location,
)

TOL = 1e-9


# ======================================================================
# public entry point
# ======================================================================
@frappe.whitelist()
def resolve(warehouse, items, direction="out", qty_by_item=None):
	"""Resolve locations for a batch of item codes in one round trip.

	`items`       JSON list of item codes (or a plain list when called from Python).
	`direction`   "out" to take stock from a location, "in" to put it away.
	`qty_by_item` optional JSON map of item_code -> qty, so the resolver can prefer a
	              location that actually covers the line and propose a split when none does.
	              against it, so re-opening a request does not fight itself.

	Returns {item_code: {mode, location, location_label, candidates, split, reason}}.
	"""
	codes = _as_list(items)
	if not warehouse or not codes or not is_enabled():
		return {}

	qty_map = frappe.parse_json(qty_by_item) if isinstance(qty_by_item, str) else (qty_by_item or {})
	direction = "in" if str(direction).lower() == "in" else "out"

	locations = _warehouse_locations(warehouse)
	balances = location_balances(warehouse, codes)
	unassigned = get_unassigned_location(warehouse)
	if direction == "out" and not _allow_unassigned_picks():
		unassigned = None

	# Two queries for the whole document rather than two per row: a Stock Entry with a
	# hundred lines resolves in one round trip.
	on_hand = bin_quantities(warehouse, codes) if direction == "out" else {}
	item_groups = _item_groups(codes) if direction == "in" else {}
	declared = _declared_locations(codes, warehouse, direction)

	out = {}
	for code in codes:
		item_balances = balances.get(code, {})
		if direction == "out":
			qty = flt(qty_map.get(code)) if qty_map else 0.0
			remainder = flt(on_hand.get(code)) - sum(flt(v) for v in item_balances.values())
			out[code] = _resolve_out(
				code, qty, locations, item_balances, unassigned, remainder,
				flt(on_hand.get(code)), declared.get(code),
			)
		else:
			out[code] = _resolve_in(
				code, locations, item_balances, unassigned, item_groups.get(code), declared.get(code)
			)
	return out


@frappe.whitelist()
def resolve_one(warehouse, item_code, direction="out", qty=0):
	"""Single-row convenience wrapper — what the grid controls call on item change."""
	if not is_enabled():
		return None
	res = resolve(warehouse, [item_code], direction, {item_code: flt(qty)})
	return res.get(item_code) or _empty("none", _("No location could be resolved."))


# ======================================================================
# outbound: which location do we take this from?
# ======================================================================
def _resolve_out(
	item_code, qty, locations, balances, unassigned, remainder, on_hand, declared=None,
):
	candidates = []

	for location, location_qty in balances.items():
		meta = locations.get(location)
		if not meta or not meta.is_active or meta.is_unassigned:
			continue
		free = flt(location_qty)
		if free <= TOL:
			continue
		candidates.append(
			{
				"location": location,
				"label": meta.label,
				"qty": free,
				"held": flt(location_qty),
				"priority": meta.pick_priority,
				"covers": qty <= TOL or free + TOL >= qty,
				"is_unassigned": 0,
				"reason": _("holds {0}").format(_n(location_qty)),
			}
		)

	# Real locations are always offered before the unassigned remainder: the whole point
	# of the ledger is to pick from a known place. A location the item declares as its
	# pick face leads — but only while it actually holds something, because a declared
	# preference is not a reason to pick from an empty shelf.
	# Order: a location that can cover the line on its own first (one location beats two),
	# then the priority someone set on it, then by name. Name rather than "biggest pile"
	# because a picker walks the racks in order, and because a stable, predictable order
	# is worth more than shaving a shelf off the occasional split.
	candidates.sort(key=lambda c: (not c["covers"], c["priority"], c["location"]))
	if declared:
		lead = next((c for c in candidates if c["location"] == declared), None)
		if lead:
			candidates.remove(lead)
			lead["reason"] = _("the item's pick location here — {0}").format(_n(lead["qty"]))
			candidates.insert(0, lead)
	real_count = len(candidates)

	loose = flt(remainder) if unassigned else 0.0
	if unassigned and loose > TOL:
		candidates.append(
			{
				"location": unassigned,
				"label": locations.get(unassigned).label if locations.get(unassigned) else unassigned,
				"qty": loose,
				"held": flt(remainder),
				"priority": 900,
				"covers": qty <= TOL or loose + TOL >= qty,
				"is_unassigned": 1,
				"reason": _("not yet put away — {0} loose in the warehouse").format(_n(loose)),
			}
		)

	if not candidates:
		if on_hand > TOL:
			return _empty(
				"none",
				_("{0} in stock here but the location ledger says none is available.").format(_n(on_hand)),
			)
		return _empty("none", _("Not in this warehouse."))

	# Exactly one real location holds it — the everyday case, and the one that should
	# never cost the operator a click.
	if real_count == 1:
		best = candidates[0]
		return _result(
			"locked" if best["covers"] else "split",
			best,
			candidates,
			_("only location holding this item"),
			_split(candidates, qty) if not best["covers"] else None,
		)

	if real_count == 0:
		best = candidates[0]  # the unassigned remainder
		return _result(
			"locked" if best["covers"] else "split",
			best,
			candidates,
			_("not put away yet — take it from unassigned stock"),
			_split(candidates, qty) if not best["covers"] else None,
		)

	best = candidates[0]
	if qty > TOL and not best["covers"]:
		return _result("split", best, candidates, _("no single location covers this line"), _split(candidates, qty))

	# A location the item declares as its pick face is an answer somebody already gave,
	# so it is not a choice to make again.
	if declared and best["location"] == declared:
		return _result(
			"suggested", best, candidates,
			_("the item's pick location in this warehouse"), None, needs_choice=False,
		)

	covering = [c for c in candidates if c["covers"] and not c["is_unassigned"]]
	reason = (
		_("highest priority location that covers this line")
		if len(covering) > 1
		else _("only location that covers this line")
	)
	return _result("suggested", best, candidates, reason, None, needs_choice=len(covering) > 1)


# ======================================================================
# inbound: where do we put this away?
# ======================================================================
def _resolve_in(item_code, locations, balances, unassigned, item_group, declared):
	def usable(location):
		meta = locations.get(location)
		return meta if meta and meta.is_active and not meta.is_unassigned else None

	# where it already lives — including locations whose balance has run down to zero,
	#    which are exactly the memory of "this item belongs on that shelf"
	occupied = [s for s in balances if usable(s)]
	if len(occupied) == 1:
		return _pin(occupied[0], locations, _("where this item is already kept"), balances)
	if len(occupied) > 1:
		ranked = sorted(occupied, key=lambda s: (locations[s].pick_priority, -flt(balances[s]), s))
		return _result(
			"suggested",
			_cand(ranked[0], locations, balances),
			[_cand(s, locations, balances) for s in ranked],
			_("already kept in {0} locations here").format(len(ranked)),
			None,
		)

	# a location that receives this item's group (or any parent group)
	by_group = _location_for_item_group(item_group, locations)
	if by_group:
		return _pin(by_group, locations, _("receives {0}").format(item_group), balances)

	# the warehouse's own receiving location (a property of the warehouse, not the item)
	receiving = next(
		(s for s, m in locations.items() if m.is_default_receiving and m.is_active and not m.is_unassigned),
		None,
	)
	if receiving:
		return _pin(receiving, locations, _("default receiving location"), balances)

	# unassigned — put-away can always fall back, it never dead-ends
	if unassigned:
		return _pin(unassigned, locations, _("no rule matched — leave it unassigned for now"), balances)
	return _empty("choose", _("This warehouse has no locations yet."))


def _item_groups(codes):
	rows = frappe.get_all(
		"Item", filters={"name": ["in", list(codes)]}, fields=["name", "item_group"],
		limit_page_length=0,
	)
	return {r.name: r.item_group for r in rows}


def _declared_locations(codes, warehouse, direction="out"):
	"""Each item's declared pick location in this warehouse."""
	# Only picking has a declared location. Putting away is a decision made at the shelf,
	# so there is nothing to declare in advance and nothing to look up here.
	if direction != "out":
		return {}
	field = "default_out"
	rows = frappe.get_all(
		"Item Default Location",
		filters={
			"parent": ["in", list(codes)],
			"parenttype": "Item",
			"warehouse": warehouse,
			field: 1,
		},
		fields=["parent", "location"],
		limit_page_length=0,
	)
	return {r.parent: r.location for r in rows}


def _location_for_item_group(item_group, locations):
	"""Nearest location whose `receives_item_group` is this group or one of its ancestors."""
	if not item_group:
		return None
	rules = {
		m.receives_item_group: s
		for s, m in locations.items()
		if m.receives_item_group and m.is_active and not m.is_unassigned
	}
	if not rules:
		return None
	node = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
	if not node:
		return rules.get(item_group)

	bounds = _group_bounds(tuple(sorted(rules)))
	# the tightest enclosing group wins
	best, best_span = None, None
	for group, location in rules.items():
		g = bounds.get(group)
		if not g or g["lft"] > node.lft or g["rgt"] < node.rgt:
			continue
		span = g["rgt"] - g["lft"]
		if best_span is None or span < best_span:
			best, best_span = location, span
	return best


def _group_bounds(groups):
	rows = frappe.get_all(
		"Item Group", filters={"name": ["in", list(groups)]}, fields=["name", "lft", "rgt"],
		limit_page_length=0,
	)
	return {r.name: {"lft": r.lft, "rgt": r.rgt} for r in rows}


# ======================================================================
# shaping helpers
# ======================================================================
def _warehouse_locations(warehouse):
	rows = frappe.get_all(
		"Warehouse Location",
		filters={"warehouse": warehouse},
		fields=[
			"name",
			"location_code",
			"location_name",
			"is_active",
			"is_unassigned",
			"is_default_receiving",
			"pick_priority",
			"receives_item_group",
			"max_qty",
		],
		limit_page_length=0,
	)
	out = {}
	for r in rows:
		r.pick_priority = r.pick_priority if r.pick_priority is not None else 10
		r.label = r.location_name or r.location_code or r.name
		out[r.name] = r
	return out


def _cand(location, locations, balances):
	meta = locations.get(location)
	qty = flt(balances.get(location))
	return {
		"location": location,
		"label": meta.label if meta else location,
		"qty": qty,
		"held": qty,
		"priority": meta.pick_priority if meta else 10,
		"covers": True,
		"is_unassigned": 1 if (meta and meta.is_unassigned) else 0,
		"reason": _("holds {0}").format(_n(qty)),
	}


def _pin(location, locations, reason, balances):
	return _result("locked", _cand(location, locations, balances), [_cand(location, locations, balances)], reason, None)


def _result(mode, best, candidates, reason, split, needs_choice=False):
	return {
		"mode": mode,
		# Several locations could supply this line and one merely leads. That is a
		# decision, not a lookup — the difference between "there is one answer" and
		# "somebody has to pick one".
		"needs_choice": bool(needs_choice),
		"location": best["location"] if best else None,
		"location_label": best["label"] if best else None,
		"is_unassigned": best.get("is_unassigned", 0) if best else 0,
		"available": best["qty"] if best else 0.0,
		"candidates": candidates,
		"split": split,
		"reason": reason,
	}


def _empty(mode, reason):
	return {
		"mode": mode,
		"needs_choice": False,
		"location": None,
		"location_label": None,
		"is_unassigned": 0,
		"available": 0.0,
		"candidates": [],
		"split": None,
		"reason": reason,
	}


def _split(candidates, qty):
	"""Greedy allocation across locations, biggest usable holding first."""
	if qty <= TOL:
		return None
	left, plan = qty, []
	for c in candidates:
		if left <= TOL:
			break
		take = min(left, c["qty"])
		if take <= TOL:
			continue
		plan.append({"location": c["location"], "label": c["label"], "qty": flt(take, 6)})
		left -= take
	if not plan:
		return None
	if left > TOL:
		plan.append({"location": None, "label": _("short"), "qty": flt(left, 6), "short": 1})
	return plan


def _allow_unassigned_picks():
	"""Once a warehouse is fully put away, picking from the remainder can be switched off."""
	return setting("allow_pick_from_unassigned")


def auto_resolve_enabled():
	"""Whether blank locations are filled in automatically on submit."""
	return setting("auto_resolve_locations")


def _as_list(items):
	if isinstance(items, str):
		items = frappe.parse_json(items)
	if isinstance(items, str):
		items = [items]
	return [i for i in (items or []) if i]


def _n(value):
	return frappe.format_value(flt(value), {"fieldtype": "Float"})


# ======================================================================
# link queries
# ======================================================================
# A "pick from" field must not offer every shelf in the warehouse. It should offer the
# shelves that actually hold the item — the same set the resolver ranks — so the list
# the operator sees and the answer the system chose come from one place.
@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def location_query(doctype, txt, searchfield, start, page_len, filters):
	filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	warehouse = filters.get("warehouse")
	item_code = filters.get("item_code")
	direction = "in" if str(filters.get("direction") or "out").lower() == "in" else "out"

	if not warehouse or not is_enabled():
		return []

	# putting away can go anywhere; taking out cannot
	if direction == "in" or not item_code:
		return _all_locations(warehouse, txt, start, page_len)

	res = resolve(warehouse, [item_code], "out", {item_code: 0}) or {}
	candidates = (res.get(item_code) or {}).get("candidates") or []
	needle = (txt or "").lower()
	rows = []
	for c in candidates:
		if needle and needle not in (c["location"] or "").lower() and needle not in (c["label"] or "").lower():
			continue
		rows.append(
			[
				c["location"],
				"{0} · {1}".format(
					_("not put away") if c.get("is_unassigned") else (c.get("label") or ""),
					_n(c["qty"]),
				),
			]
		)
	return rows[start : start + page_len]


def _all_locations(warehouse, txt, start, page_len):
	like = "%{0}%".format(txt or "")
	return frappe.db.sql(
		"""
		select name,
			case when is_unassigned = 1 then %s
			else concat_ws(' · ', location_name, location_type) end
		from `tabWarehouse Location`
		where warehouse = %s and is_active = 1
			and (name like %s or location_code like %s or location_name like %s)
		order by is_unassigned asc, pick_priority asc, location_code asc
		limit %s offset %s
		""",
		(_("not put away yet"), warehouse, like, like, like, page_len, start),
	)
