// Isoft Location Manager on Stock Entry:
//  - the location pickers on each item row only offer locations of that row's warehouse
//  - if the row's warehouse is NOT enabled for Isoft Location Manager, no location can be set (locked)
//  - a row whose item lives in exactly one location fills that location in by itself, so the
//    common case costs nobody a click; anything left blank is resolved again on submit
frappe.ui.form.on('Stock Entry', {
	setup: function (frm) {
		frm._ip_enabled = [];
		frm._ip_all = true;
		const ctx = (whfield, direction) => (doc, cdt, cdn) => {
			const row = locals[cdt][cdn] || {};
			const wh = row[whfield];
			const enabled = frm._ip_all || (frm._ip_enabled || []).indexOf(wh) !== -1;
			return { warehouse: enabled ? wh : '', item_code: row.item_code, direction };
		};
		frm.set_query('custom_from_location', 'items',
			ip_location_query(ctx('s_warehouse', 'out')));
		frm.set_query('custom_to_location', 'items',
			ip_location_query(ctx('t_warehouse', 'in')));
	},

	from_warehouse: function (frm) { ip_sweep(frm); },
	to_warehouse: function (frm) { ip_sweep(frm); },
	stock_entry_type: function (frm) { ip_sweep(frm); },
	purpose: function (frm) { ip_sweep(frm); },

	refresh: function (frm) {
		if (!window.isoft_warehouse_location_management) return;
		if (isoft_warehouse_location_management.toggle_grid_locations) {
			// custom_from_location stays hidden on purpose — "Picked From Location" says the
			// same thing and copes with a line that came off several places
			isoft_warehouse_location_management.toggle_grid_locations(frm, 'items',
				['custom_location_allocation'], 'stock_entry');
			// the target side disappears when arrivals may not be placed
			if (typeof isoft_warehouse_location_management.status !== 'function'
				|| typeof isoft_warehouse_location_management.set_grid_fields_hidden !== 'function') return;
			isoft_warehouse_location_management.status().then(function (s) {
				isoft_warehouse_location_management.set_grid_fields_hidden(frm, 'items', ['custom_to_location'],
					!(s.enabled && s.stock_entry && s.location_on_in));
			});
		}
		if (isoft_warehouse_location_management.mount_picking_sheet) isoft_warehouse_location_management.mount_picking_sheet(frm);
		if (!isoft_warehouse_location_management.mount_grid_split) return;
		// the split is always about what is taken out, so it hangs off the source side
		isoft_warehouse_location_management.mount_grid_split(frm, {
			table_field: 'items',
			cdt: 'Stock Entry Detail',
			warehouse_field: 's_warehouse',
			direction: 'out',
			feature: 'stock_entry',
		});
	},

	onload: function (frm) {
		frappe.call({
			method: 'isoft_warehouse_location_management.isoft_location_manager.api.get_enabled_warehouses',
			callback: function (r) {
				frm._ip_enabled = r.message || [];
				frm._ip_all = frm._ip_enabled.length === 0; // empty table => all enabled
			},
		});
	},
});

frappe.ui.form.on('Stock Entry Detail', {
	s_warehouse: function (frm, cdt, cdn) {
		ip_guard_location(frm, cdt, cdn, 's_warehouse', 'custom_from_location');
		ip_resolve(frm, cdt, cdn);
	},
	t_warehouse: function (frm, cdt, cdn) {
		ip_guard_location(frm, cdt, cdn, 't_warehouse', 'custom_to_location');
		ip_resolve(frm, cdt, cdn);
	},
	item_code: function (frm, cdt, cdn) { ip_resolve(frm, cdt, cdn); },
	qty: function (frm, cdt, cdn) { ip_resolve(frm, cdt, cdn); },
	items_add: function (frm, cdt, cdn) { ip_resolve(frm, cdt, cdn); },
	custom_from_location: function (frm, cdt, cdn) { ip_guard_location(frm, cdt, cdn, 's_warehouse', 'custom_from_location'); },
	custom_to_location: function (frm, cdt, cdn) { ip_guard_location(frm, cdt, cdn, 't_warehouse', 'custom_to_location'); },
});

// Resolve every row. The parent's warehouse fields are applied to rows in ways that do
// not always reach the child trigger, so a sweep is the only reliable moment.
function ip_sweep(frm) {
	(frm.doc.items || []).forEach((row) => ip_resolve(frm, row.doctype, row.name));
}

function ip_enabled_for(frm, warehouse) {
	return frm._ip_all || (frm._ip_enabled || []).indexOf(warehouse) !== -1;
}

// Ask the resolver where this row's item is kept, and fill the location in when the
// answer is not in doubt. A location the user typed themselves is never overwritten.
function ip_resolve(frm, cdt, cdn) {
	if (!window.isoft_warehouse_location_management || !isoft_warehouse_location_management.resolve_grid_row) return;
	const row = locals[cdt][cdn];
	if (!row || !row.item_code) return;

	if (row.s_warehouse && !row.custom_from_location && ip_enabled_for(frm, row.s_warehouse)) {
		isoft_warehouse_location_management.resolve_grid_row({
			frm, cdt, cdn,
			item_field: 'item_code',
			warehouse_field: 's_warehouse',
			location_field: 'custom_from_location',
			qty_field: 'qty',
			direction: 'out',
		});
	}
	// The target side is deliberately left alone. Where something is put away is decided
	// at the shelf by whoever is holding it, so it is never guessed at — and a row left
	// blank is not a gap, it means the goods arrived and are not on a location yet.
}

function ip_guard_location(frm, cdt, cdn, whfield, secfield) {
	const row = locals[cdt][cdn];
	if (!row[secfield]) return;
	const wh = row[whfield];
	if (!ip_enabled_for(frm, wh)) {
		frappe.model.set_value(cdt, cdn, secfield, null);
		frappe.show_alert({
			message: __('Location cleared — {0} is not enabled for Isoft Location Manager.', [wh || '']),
			indicator: 'orange',
		});
	}
}

frappe.ui.form.on('Stock Entry Detail', {
	form_render: function (frm, cdt, cdn) {
		if (!window.isoft_warehouse_location_management || !isoft_warehouse_location_management.mount_split_button) return;
		isoft_warehouse_location_management.mount_split_button({
			frm, cdt, cdn,
			warehouse_field: 's_warehouse',
			qty_field: 'qty',
			direction: 'out',
			feature: 'stock_entry',
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
