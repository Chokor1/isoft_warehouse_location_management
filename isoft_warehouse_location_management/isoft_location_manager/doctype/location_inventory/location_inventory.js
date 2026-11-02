// Copyright (c) 2026, ISOFT LDA
// Author: Abbass Chokor
// For license information, please see license.txt

frappe.ui.form.on('Location Inventory', {
	refresh(frm) {
		// a count cancels its own reconciliation and movement, in that order, in on_cancel
		isoft_warehouse_location_management.allow_mirror_cancel(frm, ['Stock Reconciliation']);
	},

	setup(frm) {
		// only a real, active location can be counted; unassigned stock is what is left over
		frm.set_query('location', () => ({
			filters: Object.assign({ is_active: 1, is_unassigned: 0 },
				frm.doc.warehouse ? { warehouse: frm.doc.warehouse } : {}),
		}));
		// a quantity alone cannot say which serial numbers or batches are on the shelf
		frm.set_query('item_code', 'items', () => ({
			filters: { is_stock_item: 1, has_serial_no: 0, has_batch_no: 0 },
		}));
	},
});
