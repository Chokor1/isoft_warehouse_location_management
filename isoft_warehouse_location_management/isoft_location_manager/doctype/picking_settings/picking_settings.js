// Copyright (c) 2026, ISOFT LDA
// Author: Abbass Chokor
// For license information, please see license.txt

frappe.ui.form.on('Picking Settings', {
	refresh: function (frm) {
		frm.trigger('enabled');
	},

	enabled: function (frm) {
		if (frm.doc.enabled) {
			frm.set_intro(
				__('Isoft Location Manager is on. Locations are captured and resolved on the documents enabled below.'),
				'green'
			);
		} else {
			frm.set_intro(
				__(
					'Isoft Location Manager is off. No stock document is validated, mirrored or asked for a location, ' +
						'and the picking screens are closed. Existing location data is kept.'
				),
				'orange'
			);
		}
	},
});
