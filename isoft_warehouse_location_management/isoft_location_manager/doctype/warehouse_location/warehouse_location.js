// Copyright (c) 2026, ISOFT LDA
// Author: Abbass Chokor
// For license information, please see license.txt

frappe.ui.form.on('Warehouse Location', {
	setup: function (frm) {
		// only the warehouses Isoft Location Manager is switched on for
		frm.set_query('warehouse', window.isoft_warehouse_location_management && isoft_warehouse_location_management.warehouse_query
			? isoft_warehouse_location_management.warehouse_query(frm)
			: function () { return { filters: { is_group: 0 } }; });

		// a zone lives in one warehouse, so only that warehouse's zones are offered
		frm.set_query('zone', function () {
			return { filters: { warehouse: frm.doc.warehouse || '', is_active: 1 } };
		});
	},

	refresh: function (frm) {
		if (frm.doc.is_unassigned) {
			frm.set_intro(
				__(
					'This is the warehouse’s Unassigned Stock location. Its quantity is not stored — it is ' +
						'whatever the warehouse holds minus what the real locations hold, so everything not yet ' +
						'put away shows up here on its own. It cannot be renamed or deleted.'
				),
				'orange'
			);
			['location_code', 'location_name', 'warehouse', 'location_type', 'is_active',
			 'is_default_receiving', 'pick_priority', 'receives_item_group'].forEach((f) =>
				frm.set_df_property(f, 'read_only', 1)
			);
			return;
		}

		if (!frm.is_new() && frm.doc.warehouse) {
			frm.add_custom_button(__('Open in Picking'), function () {
				frappe.set_route('isoft-location-manager');
			});
		}
	},

	location_code: function (frm) {
		if (frm.doc.location_code) {
			frm.set_value('location_code', frm.doc.location_code.trim().toUpperCase());
		}
		if (!frm.doc.location_name && frm.doc.location_code) {
			frm.set_value('location_name', frm.doc.location_code);
		}
	},
});
