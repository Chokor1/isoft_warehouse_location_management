// The Picking Sheet button.
//
// A shipment is prepared by somebody who is not the person who typed it. They need one
// page: what to fetch, how much, and from which location — and nothing else. This puts
// that page one click away from the document it belongs to.
//
// It appears only when there is something to pick: the module is on, the document really
// takes stock out, and it does so from a warehouse this app runs in. A Stock Entry that
// only receives has nothing to fetch, so it gets no button.

isoft_warehouse_location_management.mount_picking_sheet = function (frm) {
	if (frm.is_new() || frm.doc.docstatus === 2) return;

	isoft_warehouse_location_management.promise(
		{
			method: 'isoft_warehouse_location_management.isoft_location_manager.picking_sheet.is_available',
			args: { doctype: frm.doc.doctype, name: frm.doc.name },
		},
		{ available: false }
	).then((r) => {
		if (!r || !r.available || !r.format) return;
		frm.add_custom_button(__('Picking Sheet'), () => {
			// Opened as a printable page rather than routed to in the desk: the person
			// using it is on their way to the racks, and what they want is paper.
			const url = '/printview?doctype=' + encodeURIComponent(frm.doc.doctype)
				+ '&name=' + encodeURIComponent(frm.doc.name)
				+ '&format=' + encodeURIComponent(r.format)
				+ '&no_letterhead=1&trigger_print=1'
				+ '&_lang=' + encodeURIComponent(frappe.boot.lang || 'en');
			window.open(url, '_blank');
		});
	});
};
