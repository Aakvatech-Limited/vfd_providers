// Copyright (c) 2026, Aakvatech Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on("DIRM VFD Settings", {
	get_token: (frm) => {
		frappe.call({
			method: "get_session_token",
			doc: frm.doc,
			freeze: true,
			freeze_message: __("Please Wait..."),
			callback: (r) => {
				if (r.message) {
					frm.refresh();
				}
			},
		});
	},
});
