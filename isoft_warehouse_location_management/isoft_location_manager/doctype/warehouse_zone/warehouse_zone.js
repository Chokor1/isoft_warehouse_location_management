frappe.ui.form.on('Warehouse Zone', {
	setup(frm) {
		frm.set_query('warehouse', () => ({ filters: { is_group: 0 } }));
	},
});
