// Isoft Location Manager on Purchase Receipt and Purchase Invoice.
//
// Goods arriving get an optional put-away location, and it is always chosen by hand.
// Where something goes is a decision somebody makes standing at the shelf — guessing at
// it would put stock on a location nobody visited. So the field starts empty and stays
// empty until it is filled in, and a line left blank simply means the goods are in the
// warehouse and not yet on a location: unassigned stock. A purchase is never refused
// over a shelf.
//
// A return sends goods back to the supplier. That takes stock *out*, so it is resolved
// and checked like any other outbound line, on the server.

// Never begin a statement with `[` or `(` in a doctype script. These files are
// *concatenated* onto whatever erpnext already contributes for the doctype, and
// erpnext's purchase_invoice.js ends `})` with no semicolon — so a leading bracket is
// glued on as a property access on it, and the form dies before it renders.
const IP_PURCHASE_DOCTYPES = ['Purchase Receipt', 'Purchase Invoice'];

IP_PURCHASE_DOCTYPES.forEach(function (dt) {
	frappe.ui.form.on(dt, {
		setup: function (frm) {
			frm.set_query('custom_to_location', 'items', ip_purchase_query(
				(doc, cdt, cdn) => {
					const row = locals[cdt][cdn] || {};
					return { warehouse: row.warehouse, item_code: row.item_code, direction: 'in' };
				}));
		},

		refresh: function (frm) {
			if (!window.isoft_warehouse_location_management || !isoft_warehouse_location_management.toggle_grid_locations) return;
			isoft_warehouse_location_management.toggle_grid_locations(frm, 'items', ['custom_to_location'], 'purchase');
		},
	});
});

// A set_query that degrades instead of throwing.
//
// location_control.js ships in app_include_js and is cached by the browser against a
// build version. If a stale copy is in play, calling a helper it does not have would
// throw inside setup and take the whole form down with it — an app that adds a field
// must never be able to break the document it is added to.
function ip_purchase_query(get_ctx) {
	if (window.isoft_warehouse_location_management && typeof isoft_warehouse_location_management.location_query === 'function') {
		return isoft_warehouse_location_management.location_query(get_ctx);
	}
	return function (doc, cdt, cdn) {
		const c = (get_ctx && get_ctx(doc, cdt, cdn)) || {};
		return { filters: { warehouse: c.warehouse || '__none__', is_active: 1 } };
	};
}
