# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
# For license information, please see license.txt
#
# A Location Inventory is a count of one location.
#
# The counter reads what the system believes is on the location, writes down what is
# physically there, and on submit the difference becomes real. A Stock Reconciliation
# corrects the warehouse total, and a Location Stock Movement moves the same difference
# between the location and unassigned stock. Together they keep the partition exact:
# the warehouse changes by exactly what the location changed by, and unassigned stock
# is left where it was.
#
# Only lines that were actually counted are posted. A blank is "not counted yet", which
# is not zero, and treating the two alike would write off every item the counter simply
# had not reached.

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, nowdate, nowtime

from isoft_warehouse_location_management.isoft_location_manager.api import (
	is_warehouse_enabled,
	log_activity,
	require_enabled,
)
from isoft_warehouse_location_management.isoft_location_manager.doctype.location_stock.location_stock import (
	get_balance,
)
from isoft_warehouse_location_management.isoft_location_manager.doctype.warehouse_location.warehouse_location import (
	get_unassigned_location,
)

TOL = 1e-9


class LocationInventory(Document):
	def validate(self):
		if self.docstatus == 0:
			require_enabled(_("count a location"))
		self._check_location()
		self._refresh_rows()
		self._summarise()
		if self.docstatus == 0 and self.is_new():
			self._warn_other_drafts()

	def before_submit(self):
		# A count is posted against the stock as it is when it is posted. Stock may have
		# moved since the sheet was opened, which is why the system quantity is read again
		# here; backdating would reconcile against a balance nobody counted.
		self.posting_date = nowdate()
		self.posting_time = nowtime()
		self._refresh_rows()
		self._summarise()
		if not self.counted_lines:
			frappe.throw(
				_("Nothing has been counted yet. Enter a quantity on at least one line."),
				title=_("Nothing Counted"),
			)

		# Refuse rather than guess. A line whose stock moved after it was counted cannot be
		# posted honestly either way: against the old quantity it undoes the movement, and
		# against the new one it reads a count nobody took.
		moved = []
		for r in self.items:
			if not cint(r.is_counted):
				continue
			now = get_balance(self.location, r.item_code)
			if abs(now - flt(r.system_qty)) > 1e-6:
				moved.append(_("{0} ({1} when counted, {2} now)").format(r.item_code, flt(r.system_qty), flt(now)))
		if moved:
			frappe.throw(
				_("Stock moved on {0} after it was counted: {1}. Posting now would adjust against "
				  "quantities nobody counted. Save the draft to see the new quantities, then count "
				  "those lines again.").format(self.location_code, "; ".join(moved)),
				title=_("Stock Moved During the Count"),
			)

	def on_submit(self):
		lines = [r for r in self.items if cint(r.is_counted) and abs(flt(r.difference)) > TOL]
		if lines:
			# The reconciliation goes first, so an item found on the shelf is already part of
			# the warehouse — and so available as unassigned stock — when the movement puts
			# it on the location.
			reconciliation = self._post_reconciliation(lines)
			movement = self._post_movement(lines)
			self.db_set("stock_reconciliation", reconciliation)
			self.db_set("location_movement", movement)
		log_activity(
			"Movement", "Counted", self.name, warehouse=self.warehouse,
			reference_type="Location Inventory",
			message=_("{0}: {1} counted, {2} with a difference").format(
				self.location_code, self.counted_lines, self.difference_lines
			),
		)

	def on_cancel(self):
		# Undone in reverse. Both are cancelled here, before Frappe looks for submitted
		# documents still pointing at this one — which it only does after on_cancel.
		if self.location_movement:
			movement = frappe.get_doc("Location Stock Movement", self.location_movement)
			if movement.docstatus == 1:
				movement.flags.ignore_permissions = True
				movement.cancel()
		if self.stock_reconciliation:
			reconciliation = frappe.get_doc("Stock Reconciliation", self.stock_reconciliation)
			if reconciliation.docstatus == 1:
				reconciliation.flags.ignore_permissions = True
				reconciliation.cancel()
		log_activity(
			"Movement", "Cancelled count", self.name, warehouse=self.warehouse,
			reference_type="Location Inventory",
		)

	# ------------------------------------------------------------------
	# checks
	# ------------------------------------------------------------------
	def _check_location(self):
		if not self.location:
			frappe.throw(_("Choose the location being counted."))
		loc = frappe.db.get_value(
			"Warehouse Location",
			self.location,
			["warehouse", "location_code", "is_active", "is_unassigned"],
			as_dict=True,
		)
		if not loc:
			frappe.throw(_("Location {0} does not exist.").format(self.location))
		if loc.is_unassigned:
			frappe.throw(
				_("Unassigned stock is whatever is not on a location, so it cannot be counted as "
				  "one. Count the locations; what is left over is unassigned.")
			)
		if not loc.is_active:
			frappe.throw(_("Location {0} is inactive.").format(loc.location_code))
		if self.warehouse and self.warehouse != loc.warehouse:
			frappe.throw(
				_("Location {0} belongs to {1}, not {2}.").format(loc.location_code, loc.warehouse, self.warehouse)
			)
		self.warehouse = loc.warehouse
		if not is_warehouse_enabled(self.warehouse):
			frappe.throw(_("{0} is not enabled in Isoft Location Manager.").format(self.warehouse))
		self.location_code = loc.location_code
		self.company = frappe.db.get_value("Warehouse", self.warehouse, "company")
		if not self.posting_date:
			self.posting_date = nowdate()
		if not self.counted_by:
			self.counted_by = frappe.session.user

	def _refresh_rows(self):
		# The quantity a line was counted against is fixed when it is counted. Re-reading it
		# on every save would quietly absorb anything that moved in between, and the count
		# would then be posted against stock the counter never saw.
		before = None if self.is_new() else self.get_doc_before_save()
		previous = {r.item_code: r for r in (before.items if before else [])}
		seen = {}
		for row in self.items:
			if not row.item_code:
				frappe.throw(_("Row #{0}: choose an item.").format(row.idx))
			if row.item_code in seen:
				frappe.throw(
					_("Row #{0}: {1} is already on row {2}.").format(row.idx, row.item_code, seen[row.item_code])
				)
			seen[row.item_code] = row.idx

			item = frappe.db.get_value(
				"Item",
				row.item_code,
				["item_name", "stock_uom", "is_stock_item", "has_serial_no", "has_batch_no"],
				as_dict=True,
			)
			if not item:
				frappe.throw(_("Row #{0}: there is no item {1}.").format(row.idx, row.item_code))
			if not item.is_stock_item:
				frappe.throw(_("Row #{0}: {1} is not a stock item.").format(row.idx, row.item_code))
			if item.has_serial_no or item.has_batch_no:
				frappe.throw(
					_("Row #{0}: {1} is tracked by {2}, and a quantity alone cannot say which ones are "
					  "there. Count it with a Stock Reconciliation that lists them.").format(
						row.idx, row.item_code, _("serial number") if item.has_serial_no else _("batch")
					)
				)

			row.item_name = item.item_name
			row.stock_uom = item.stock_uom
			current = get_balance(self.location, row.item_code)
			if not cint(row.is_counted):
				row.system_qty = current
				row.counted_qty = 0
				row.difference = 0
				continue
			if flt(row.counted_qty) < 0:
				frappe.throw(_("Row #{0}: a count cannot be less than zero.").format(row.idx))
			if not self.flags.from_sheet:
				# The count sheet sends what it showed the counter. Anything else keeps the
				# quantity this line was first counted against, or takes today's if it is new.
				prev = previous.get(row.item_code)
				row.system_qty = flt(prev.system_qty) if prev and cint(prev.is_counted) else current
			row.difference = flt(row.counted_qty) - flt(row.system_qty)

	def _summarise(self):
		counted = [r for r in self.items if cint(r.is_counted)]
		self.counted_lines = len(counted)
		self.difference_lines = len([r for r in counted if abs(flt(r.difference)) > TOL])
		self.net_difference = sum(flt(r.difference) for r in counted)

	def _warn_other_drafts(self):
		others = frappe.get_all(
			"Location Inventory",
			filters={"location": self.location, "docstatus": 0},
			pluck="name",
		)
		if others:
			frappe.msgprint(
				_("{0} is also being counted on {1}. Whichever is posted second is taken against "
				  "the stock the first one left.").format(self.location_code, ", ".join(others)),
				indicator="orange",
				alert=True,
			)

	# ------------------------------------------------------------------
	# posting
	# ------------------------------------------------------------------
	def _post_reconciliation(self, lines):
		from erpnext.stock.utils import get_stock_balance

		company = frappe.get_cached_doc("Company", self.company)
		if not company.stock_adjustment_account:
			frappe.throw(
				_("{0} has no Stock Adjustment Account, so a count difference has nowhere to be "
				  "booked. Set it on the Company.").format(self.company),
				title=_("No Adjustment Account"),
			)

		rows = []
		for r in lines:
			qty, rate = get_stock_balance(
				r.item_code, self.warehouse, self.posting_date, self.posting_time, with_valuation_rate=True
			)
			new_qty = flt(qty) + flt(r.difference)
			if new_qty < -TOL:
				frappe.throw(
					_("Row #{0}: {1} would leave {2} holding {3} in total, which is less than nothing. "
					  "The warehouse and its locations disagree about this item; check its unassigned "
					  "stock.").format(r.idx, r.item_code, self.warehouse, flt(new_qty))
				)
			rows.append(
				{
					"item_code": r.item_code,
					"warehouse": self.warehouse,
					"qty": max(new_qty, 0),
					# The count is about quantity. Valuing the difference at the rate the stock
					# already carries means no cost is invented or changed — only how many.
					"valuation_rate": flt(rate),
					"allow_zero_valuation_rate": 0 if flt(rate) else 1,
				}
			)

		reconciliation = frappe.get_doc(
			{
				"doctype": "Stock Reconciliation",
				"purpose": "Stock Reconciliation",
				# ERPNext fills current_qty and current_valuation_rate only in the form's script,
				# or server-side when this flag is set. Without it a reconciliation built in code
				# reads as if the whole quantity had been added — the ledger is right, but the
				# document is not. Every row here changes quantity, so none is removed by it.
				"auto_remove_items_with_no_change": 1,
				"company": self.company,
				"posting_date": self.posting_date,
				"posting_time": self.posting_time,
				"set_posting_time": 1,
				"expense_account": company.stock_adjustment_account,
				"cost_center": company.cost_center,
				"items": rows,
			}
		)
		reconciliation.flags.ignore_permissions = True
		reconciliation.insert(ignore_permissions=True)
		reconciliation.submit()
		return reconciliation.name

	def _post_movement(self, lines):
		unassigned = get_unassigned_location(self.warehouse)
		items = []
		for r in lines:
			found = flt(r.difference) > 0
			items.append(
				{
					"item_code": r.item_code,
					"qty": abs(flt(r.difference)),
					"source_location": unassigned if found else self.location,
					"target_location": self.location if found else unassigned,
				}
			)
		movement = frappe.get_doc(
			{
				"doctype": "Location Stock Movement",
				"entry_type": "Transfer",
				"warehouse": self.warehouse,
				"posting_date": self.posting_date,
				"posting_time": self.posting_time,
				"reference_doctype": "Location Inventory",
				"reference_sales_document": self.name,
				"remarks": _("Count of {0}").format(self.location_code),
				"items": items,
			}
		)
		movement.flags.ignore_permissions = True
		movement.insert(ignore_permissions=True)
		movement.submit()
		return movement.name
