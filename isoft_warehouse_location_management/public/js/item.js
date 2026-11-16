// Copyright (c) 2026, ISOFT LDA
// Author: Abbass Chokor
// For license information, please see license.txt

// "Stock by Location" on the Item form.
//
// ERPNext's Stock Levels panel says how much of this item each warehouse holds. The
// question people open the item to answer is usually the next one down: which shelf is
// it on, and how much of it never got put away. This adds that one level, under the
// panel that raises it, and says nothing when the item has no location-managed stock —
// an empty card on every service item would be worse than no card.

frappe.provide('isoft_warehouse_location_management');

isoft_warehouse_location_management.item_locations = function (frm) {
	if (frm.doc.__islocal || !frm.doc.is_stock_item) return;
	// a slow answer must not land on a form that has moved on to another item since
	const item = frm.doc.name;
	const token = (frm.__ip_loc_token = (frm.__ip_loc_token || 0) + 1);
	frappe.call({
		method: 'isoft_warehouse_location_management.isoft_location_manager.page'
			+ '.isoft_location_manager.isoft_location_manager.item_stock_by_location',
		args: { item_code: item },
		callback: (r) => {
			const data = r && r.message;
			if (token !== frm.__ip_loc_token || frm.docname !== item) return;
			if (!data || !(data.warehouses || []).length) return;
			frm.dashboard.add_section(
				isoft_warehouse_location_management.item_locations_html(data),
				__('Stock by Location')
			);
		},
	});
};

isoft_warehouse_location_management.item_locations_html = function (data) {
	const esc = frappe.utils.escape_html;
	const uom = esc(data.uom || '');
	const qty = (n) => `${format_number(n)} <span class="ip-iloc-uom">${uom}</span>`;

	return `<div class="ip-iloc">${(data.warehouses || []).map((w) => `
		<div class="ip-iloc-wh">
			<div class="ip-iloc-head">
				<span class="ip-iloc-name">${esc(w.warehouse)}</span>
				<span class="ip-iloc-onhand">${qty(w.on_hand)}</span>
			</div>
			<table class="ip-iloc-table"><tbody>
				${w.places.map((p) => `
					<tr>
						<td class="ip-iloc-code">${esc(p.code)}${
							p.label && p.label !== p.code
								? `<span class="ip-iloc-label">${esc(p.label)}</span>` : ''}</td>
						<td class="ip-iloc-qty">${qty(p.qty)}</td>
					</tr>`).join('')}
				${w.unassigned > 0 ? `
					<tr class="ip-iloc-loose">
						<td class="ip-iloc-code">${esc(__('Not put away'))}
							<span class="ip-iloc-label">${esc(__('still loose in this warehouse'))}</span></td>
						<td class="ip-iloc-qty">${qty(w.unassigned)}</td>
					</tr>` : ''}
				${!w.places.length && !(w.unassigned > 0) ? `
					<tr><td colspan="2" class="ip-iloc-none">${esc(__('Nothing here.'))}</td></tr>` : ''}
			</tbody></table>
		</div>`).join('')}</div>`;
};

frappe.ui.form.on('Item', {
	refresh(frm) {
		isoft_warehouse_location_management.item_locations(frm);
	},
});
