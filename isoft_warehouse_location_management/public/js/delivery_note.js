// Isoft Location Manager on Delivery Note.
//
// A shipment is where stock actually leaves the building, so it is where the location
// ledger has to be told. The keeper never has to name a shelf for an item that is only
// kept in one place — the row fills itself in, and anything still blank is resolved
// again on the server just before submit.
frappe.ui.form.on('Delivery Note', {
	setup: function (frm) {
		frm.set_query('custom_from_location', 'items', ip_location_query(
			(doc, cdt, cdn) => {
				const row = locals[cdt][cdn] || {};
				return { warehouse: row.warehouse, item_code: row.item_code,
					direction: frm.doc.is_return ? 'in' : 'out' };
			}));
	},

	refresh: function (frm) {
		if (!window.isoft_warehouse_location_management) return;
		if (!isoft_warehouse_location_management.toggle_grid_locations) return;
		isoft_warehouse_location_management.toggle_grid_locations(frm, 'items', ['custom_location_allocation'], 'delivery_note');
		if (isoft_warehouse_location_management.mount_picking_sheet) isoft_warehouse_location_management.mount_picking_sheet(frm);
		if (isoft_warehouse_location_management.mount_grid_split) {
			isoft_warehouse_location_management.mount_grid_split(frm, {
				table_field: 'items',
				cdt: 'Delivery Note Item',
				warehouse_field: 'warehouse',
				direction: frm.doc.is_return ? 'in' : 'out',
				feature: 'delivery_note',
			});
		}
	},
});

frappe.ui.form.on('Delivery Note Item', {
	item_code: function (frm, cdt, cdn) { ip_dn_resolve(frm, cdt, cdn); },
	warehouse: function (frm, cdt, cdn) { ip_dn_resolve(frm, cdt, cdn); },
	qty: function (frm, cdt, cdn) { ip_dn_resolve(frm, cdt, cdn); },
});

function ip_dn_resolve(frm, cdt, cdn) {
	if (!window.isoft_warehouse_location_management || !isoft_warehouse_location_management.resolve_grid_row) return;
	const row = locals[cdt][cdn];
	if (!row || !row.item_code || !row.warehouse || row.custom_from_location) return;
	if (frm.doc.docstatus !== 0) return;

	isoft_warehouse_location_management.resolve_grid_row({
		frm, cdt, cdn,
		item_field: 'item_code',
		warehouse_field: 'warehouse',
		location_field: 'custom_from_location',
		qty_field: 'qty',
		// a credit note puts the goods back, so it resolves like a put-away
		direction: frm.doc.is_return ? 'in' : 'out',
		feature: 'delivery_note',
	});
}

frappe.ui.form.on('Delivery Note Item', {
	form_render: function (frm, cdt, cdn) {
		if (!window.isoft_warehouse_location_management || !isoft_warehouse_location_management.mount_split_button) return;
		isoft_warehouse_location_management.mount_split_button({
			frm, cdt, cdn,
			warehouse_field: 'warehouse',
			qty_field: 'qty',
			direction: frm.doc.is_return ? 'in' : 'out',
			feature: 'delivery_note',
		});
	},
});

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
