// Copyright (c) 2026, ISOFT LDA
// Author: Abbass Chokor
// For license information, please see license.txt

frappe.ui.form.on('Warehouse Inventory', {
	setup(frm) {
		// stock is taken of a real warehouse; a group is the warehouses under it, one at a time
		frm.set_query('warehouse', () => ({ filters: { is_group: 0 } }));
	},
});
