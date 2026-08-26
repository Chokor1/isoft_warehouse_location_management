// Copyright (c) 2026, ISOFT LDA
// Author: Abbass Chokor
// For license information, please see license.txt

frappe.ui.form.on('Location Stock Movement', {
	setup: function (frm) {
		// only the warehouses Isoft Location Manager is switched on for
		frm.set_query('warehouse', window.isoft_warehouse_location_management && isoft_warehouse_location_management.warehouse_query
			? isoft_warehouse_location_management.warehouse_query(frm)
			: function () { return { filters: { is_group: 0 } }; });
		// taking out lists only what holds the item; putting away lists every shelf
		const ctx = (direction) => (doc, cdt, cdn) => {
			const row = locals[cdt][cdn] || {};
			return { warehouse: frm.doc.warehouse, item_code: row.item_code, direction };
		};
		frm.set_query('source_location', 'items', ip_location_query(ctx('out')));
		frm.set_query('target_location', 'items', ip_location_query(ctx('in')));
	},

	entry_type: function (frm) {
		frm.trigger('_toggle_section_columns');
		(frm.doc.items || []).forEach((row) => ip_lsm_resolve(frm, row.doctype, row.name));
	},

	warehouse: function (frm) {
		(frm.doc.items || []).forEach((row) => ip_lsm_resolve(frm, row.doctype, row.name));
	},

	refresh: function (frm) {
		frm.trigger('_toggle_section_columns');
		if (frm.doc.docstatus === 0) {
			frm.set_intro(
				__(
					'A movement re-shelves stock inside the warehouse — it never changes the warehouse total. ' +
						'Stock In takes from Unassigned Stock, Stock Out puts back into it.'
				),
				'blue'
			);
		}
	},

	_toggle_section_columns: function (frm) {
		const t = frm.doc.entry_type;
		frm.fields_dict.items.grid.update_docfield_property(
			'source_location',
			'reqd',
			t === 'Stock Out' || t === 'Transfer'
		);
		frm.fields_dict.items.grid.update_docfield_property(
			'target_location',
			'reqd',
			t === 'Stock In' || t === 'Transfer'
		);
		frm.fields_dict.items.grid.toggle_display('source_location', t !== 'Stock In');
		frm.fields_dict.items.grid.toggle_display('target_location', t !== 'Stock Out');
		frm.refresh_field('items');
	},
});

frappe.ui.form.on('Location Stock Movement Item', {
	item_code: function (frm, cdt, cdn) { ip_lsm_resolve(frm, cdt, cdn); },
	qty: function (frm, cdt, cdn) { ip_lsm_resolve(frm, cdt, cdn); },
});

// Fill in the obvious end of the movement: where the item is kept when taking it out,
// where it belongs when putting it away.
function ip_lsm_resolve(frm, cdt, cdn) {
	if (!window.isoft_warehouse_location_management || !isoft_warehouse_location_management.resolve_grid_row) return;
	const row = locals[cdt][cdn];
	if (!row || !row.item_code || !frm.doc.warehouse) return;

	// the grid row has no warehouse of its own — the document's warehouse is the one
	row.__ip_warehouse = frm.doc.warehouse;

	const t = frm.doc.entry_type;
	if ((t === 'Stock Out' || t === 'Transfer') && !row.source_location) {
		isoft_warehouse_location_management.resolve_grid_row({
			frm, cdt, cdn,
			item_field: 'item_code',
			warehouse_field: '__ip_warehouse',
			location_field: 'source_location',
			qty_field: 'qty',
			direction: 'out',
		});
	}
	// A Transfer's destination is the whole point of the document — never guess it,
	// and never risk landing on the location the row is already taking from.
	if (t === 'Stock In' && !row.target_location) {
		isoft_warehouse_location_management.resolve_grid_row({
			frm, cdt, cdn,
			item_field: 'item_code',
			warehouse_field: '__ip_warehouse',
			location_field: 'target_location',
			qty_field: 'qty',
			direction: 'in',
		});
	}
}

// A set_query that degrades instead of throwing.
//
// The location_control.js helper ships in app_include_js and is cached by the browser against a
// build version. If a stale copy is in play, calling a helper it does not have would
// throw inside setup and take the whole form down with it — an app that adds a field
// must never be able to break the document it is added to.
function ip_location_query(get_ctx) {
	if (window.isoft_warehouse_location_management && typeof isoft_warehouse_location_management.location_query === 'function') {
		return isoft_warehouse_location_management.location_query(get_ctx);
	}
	return function (doc, cdt, cdn) {
		const c = (get_ctx && get_ctx(doc, cdt, cdn)) || {};
		return { filters: { warehouse: c.warehouse || '__none__', is_active: 1 } };
	};
}
