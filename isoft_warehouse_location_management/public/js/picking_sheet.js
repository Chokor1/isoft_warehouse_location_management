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
			//
			// The sheet is carried into the warehouse *before* the document is submitted
			// — that is the whole point of it — but Frappe refuses to print a draft of a
			// submittable doctype unless Print Settings says otherwise, and refuses with
			// a PermissionError ("Not allowed to print draft documents"), which reads as
			// though the user lacks a right. printview takes its print settings from the
			// request, so this one page asks for the one it needs instead of the site
			// being opened up for every draft of every doctype.
			const url = '/printview?doctype=' + encodeURIComponent(frm.doc.doctype)
				+ '&name=' + encodeURIComponent(frm.doc.name)
				+ '&format=' + encodeURIComponent(r.format)
				+ '&no_letterhead=1&trigger_print=1'
				+ '&settings=' + encodeURIComponent(JSON.stringify({ allow_print_for_draft: 1 }))
				+ '&_lang=' + encodeURIComponent(frappe.boot.lang || 'en');
			window.open(url, '_blank');
		});
	});
};
