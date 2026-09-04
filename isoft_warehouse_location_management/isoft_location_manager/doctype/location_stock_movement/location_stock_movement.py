# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt
#
# A Location Stock Movement repartitions a warehouse's stock across its locations.
# It never changes the warehouse total, and never posts a GL entry or Stock Ledger
# Entry. Stock In takes from the Unassigned Stock location, Stock Out puts back into
# it, and Transfer moves between two named locations — so all three are the same
# operation with different ends filled in.

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from isoft_warehouse_location_management.isoft_location_manager.doctype.location_stock.location_stock import (
	apply_delta,
	get_balance,
	unassigned_qty,
)
from isoft_warehouse_location_management.isoft_location_manager.doctype.warehouse_location.warehouse_location import (
	get_unassigned_location,
)

TOL = 1e-9


class LocationStockMovement(Document):
	def validate(self):
		if self.docstatus == 0:
			from isoft_warehouse_location_management.isoft_location_manager.api import require_enabled

			require_enabled(_("post location movements"))
		if not self.posting_time:
			self.posting_time = frappe.utils.nowtime()
		self._fill_implicit_sections()
		self._validate_rows()
		self._validate_availability()

	def on_submit(self):
		self._apply(direction=1)
		self._log(self.entry_type)

	def on_cancel(self):
		self._apply(direction=-1, reversing=True)
		self._log("Cancelled " + (self.entry_type or ""))

	def _log(self, action):
		from isoft_warehouse_location_management.isoft_location_manager.api import log_activity

		log_activity(
			"Movement", action, self.name, warehouse=self.warehouse,
			reference_type="Location Stock Movement",
			message=_("{0} item line(s)").format(len(self.items)),
		)

	# ------------------------------------------------------------------
	# the implicit unassigned side
	# ------------------------------------------------------------------
	def _fill_implicit_sections(self):
		"""Make the Unassigned counterpart explicit so every row reads as a transfer."""
		if not self.warehouse:
			return
		unassigned = None
		for row in self.items:
			if self.entry_type == "Stock In" and not row.source_location:
				unassigned = unassigned or get_unassigned_location(self.warehouse)
				row.source_location = unassigned
			elif self.entry_type == "Stock Out" and not row.target_location:
				unassigned = unassigned or get_unassigned_location(self.warehouse)
				row.target_location = unassigned

	# ------------------------------------------------------------------
	# validation
	# ------------------------------------------------------------------
	def _validate_rows(self):
		if not self.items:
			frappe.throw(_("Add at least one item row."))

		for row in self.items:
			if flt(row.qty) <= 0:
				frappe.throw(_("Row #{0}: Qty must be greater than zero.").format(row.idx))

			if self.entry_type == "Stock In" and not row.target_location:
				frappe.throw(_("Row #{0}: To Location is required for Stock In.").format(row.idx))
			if self.entry_type == "Stock Out" and not row.source_location:
				frappe.throw(_("Row #{0}: From Location is required for Stock Out.").format(row.idx))
			if self.entry_type == "Transfer" and not (row.source_location and row.target_location):
				frappe.throw(
					_("Row #{0}: Both From and To Location are required for Transfer.").format(row.idx)
				)
			if row.source_location and row.source_location == row.target_location:
				frappe.throw(_("Row #{0}: From and To Location must differ.").format(row.idx))

			source = self._section(row.source_location, row.idx, _("From"))
			target = self._section(row.target_location, row.idx, _("To"))

			if source and target and source.is_unassigned and target.is_unassigned:
				frappe.throw(_("Row #{0}: nothing to record — both ends are unassigned stock.").format(row.idx))

	def _section(self, name, idx, side):
		if not name:
			return None
		sec = frappe.db.get_value(
			"Warehouse Location",
			name,
			["name", "warehouse", "is_active", "is_unassigned", "location_name"],
			as_dict=True,
		)
		if not sec:
			frappe.throw(_("Row #{0}: Location {1} does not exist.").format(idx, name))
		if sec.warehouse != self.warehouse:
			frappe.throw(
				_("Row #{0}: {1} Location {2} belongs to {3}, not {4}.").format(
					idx, side, name, sec.warehouse, self.warehouse
				)
			)
		if not sec.is_active:
			frappe.throw(_("Row #{0}: Location {1} is inactive.").format(idx, name))
		return sec


	def _validate_availability(self):
		"""Every source must actually be able to give up what the row takes.

		For a real location that is its own balance; for unassigned stock it is
		`Bin.actual_qty - sum(location balances)`, which is what the old Bin cap check
		amounted to — just stated in the direction the operator thinks in.
		"""
		# A document that has already shipped goods sets this to "Warn": the sale is a
		# fact, so a short location is a reporting problem, not a reason to fail it.
		mode = self.flags.get("picking_validation_mode") or (
			frappe.db.get_single_value("Picking Settings", "stock_validation") or "Block"
		)
		if mode == "Off":
			return

		# net demand per (source, item), so two rows off the same shelf are caught together
		demand = {}
		for row in self.items:
			if not row.source_location:
				continue
			demand[(row.source_location, row.item_code)] = (
				demand.get((row.source_location, row.item_code), 0) + flt(row.qty)
			)
			# a row that puts stock back into the same location within this document
			if row.target_location:
				key = (row.target_location, row.item_code)
				demand[key] = demand.get(key, 0) - flt(row.qty)

		for (location, item_code), qty in demand.items():
			if qty <= TOL:
				continue
			is_unassigned_src = frappe.db.get_value("Warehouse Location", location, "is_unassigned")
			available = (
				unassigned_qty(self.warehouse, item_code)
				if is_unassigned_src
				else get_balance(location, item_code)
			)
			if qty > available + TOL:
				if is_unassigned_src:
					msg = _(
						"Item {0}: only {1} is still unassigned in {2}. The rest is already put away in locations."
					).format(item_code, flt(available), self.warehouse)
				else:
					msg = _("Item {0}: location {1} holds {2}, this document takes {3}.").format(
						item_code, location, flt(available), flt(qty)
					)
				if mode == "Warn":
					frappe.msgprint(msg, indicator="orange", alert=True)
				else:
					frappe.throw(msg, title=_("Not Enough in Location"))

	# ------------------------------------------------------------------
	# balance application
	# ------------------------------------------------------------------
	def _apply(self, direction, reversing=False):
		"""direction = +1 on submit, -1 on cancel.

		Applying to an unassigned location is a no-op — its quantity is derived — so a
		Stock In only credits its target and a Stock Out only debits its source, exactly
		as before, but now the arithmetic is stated as a transfer.
		"""
		for row in self.items:
			qty = flt(row.qty) * direction
			if qty >= 0:
				giver, taker = row.source_location, row.target_location
			else:
				giver, taker, qty = row.target_location, row.source_location, -qty

			moved = qty
			if reversing:
				# A cost-free mirror must never make a real document impossible to cancel.
				# If the stock has since moved on, reverse what is still there and say so.
				available = self._available(giver, row.item_code)
				if available < qty - TOL:
					moved = max(available, 0.0)
					frappe.msgprint(
						_(
							"Location {0} only still holds {1} of the {2} {3} this document put there — "
							"the rest had already been moved on, so it was left where it is."
						).format(giver, flt(moved), flt(qty), row.item_code),
						indicator="orange",
						alert=True,
					)
			if moved <= TOL:
				continue
			apply_delta(self.warehouse, giver, row.item_code, -moved)
			apply_delta(self.warehouse, taker, row.item_code, moved)

	def _available(self, location, item_code):
		"""What a location can still give up. Unassigned stock always absorbs."""
		if not location or frappe.db.get_value("Warehouse Location", location, "is_unassigned"):
			return float("inf")
		return get_balance(location, item_code)
