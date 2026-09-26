// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

// CR-001 — the client's two ad-hoc Address scripts, ported into the app.
//
// They were Client Script records on the live site, written by another developer
// and owned by nobody's repository:
//
//   "Get SPL Full Address"  opens maps.splonline.com.sa for the Short Address
//   "Address Fetching"      splits a pasted national address into the fields
//
// The client's own words were "if you want we can merge it into the code", and
// the reason to take that offer is in the same sentence they used about the rest
// of the site: a record that exists only in the database is invisible to review,
// to tests and to the next migrate.
//
// 🔴 WHAT THIS FILE MUST NOT DO IS RUN ALONGSIDE THEM. Both register on
// `Address.refresh`, so with the Client Scripts still enabled the form grows TWO
// "Get SPL Full Address" buttons and runs the parser twice on one paste. The
// switch below is what keeps the two apart: this file is inert until
// `cr_001_spl_address` is on for the site, and `patches/disable_ported_address_scripts.py`
// disables the Client Scripts on the same site in the same migrate.
//
// ⚠️ NO API KEY, AND THAT IS THE DESIGN, NOT A GAP. SPL's address API is a paid,
// registered service; the flow the client actually uses is to open the SPL map,
// copy the full address line, and paste it back. OQ-2 asks whether a key is
// available — until it is, the button opens the page and the parser reads what
// comes back, which is exactly what the scripts being replaced did.

frappe.provide("yht");

yht.address = {
	// The SPL national address arrives as one comma-separated line:
	//
	//   RQAA2929, 6823 Prince Sultan Road, 2929, Al Olaya, Riyadh, Riyadh, 12345
	//      0            1                    2        3         4       5      6
	//
	// Index 1 carries the building number and the street glued together, which is
	// the only part that needs unpicking.
	MIN_PARTS: 7,
	BUILDING_AND_STREET: /^(\d{4})\s+(.*)$/,

	enabled() {
		return ((frappe.boot && frappe.boot.yht_features) || []).indexOf("cr_001_spl_address") !== -1;
	},

	parse(line) {
		const parts = String(line || "")
			.split(",")
			.map((part) => part.trim());
		if (parts.length < yht.address.MIN_PARTS) {
			return null;
		}

		const second = parts[1] || "";
		const match = second.match(yht.address.BUILDING_AND_STREET);

		return {
			custom_short_address: (parts[0] || "").trim().toUpperCase(),
			address_title: (parts[0] || "").trim().toUpperCase(),
			custom_building_number: match ? match[1] : "",
			address_line1: match ? match[2].trim() : second,
			custom_additional_number: parts[2] || "",
			// parts[3] is the DISTRICT, and `custom_area` is the field ZATCA reads
			// for it — see `address_district`. This assignment is the reason CR-002
			// resolved the way it did.
			custom_area: parts[3] || "",
			city: parts[4] || "",
			state: parts[5] || "",
			pincode: parts[6] || "",
		};
	},

	splUrl(shortAddress) {
		const q = encodeURIComponent(shortAddress);
		return `https://maps.splonline.com.sa/?search=${q}&component=${q}`;
	},
};

frappe.ui.form.on("Address", {
	refresh(frm) {
		if (!yht.address.enabled()) {
			return;
		}
		frm.add_custom_button(__("Get SPL Full Address"), () => {
			const shortAddress = (frm.doc.custom_short_address || "").trim().toUpperCase();
			if (!shortAddress) {
				frappe.msgprint({
					title: __("Short Address Required"),
					message: __("Enter the four-letter, four-digit Short Address first, for example {0}.", [
						"<code>RQAA2929</code>",
					]),
					indicator: "orange",
				});
				return;
			}
			window.open(yht.address.splUrl(shortAddress), "_blank", "noopener");
			frappe.show_alert({
				message: __("SPL opened. Copy the full address line and paste it into National Address Full Data."),
				indicator: "green",
			});
		});
	},

	custom_national_address_full_data(frm) {
		if (!yht.address.enabled() || !frm.doc.custom_national_address_full_data) {
			return;
		}

		const values = yht.address.parse(frm.doc.custom_national_address_full_data);
		if (!values) {
			frappe.msgprint({
				title: __("Incomplete National Address"),
				message: __("Expected at least {0} comma-separated parts from SPL.", [yht.address.MIN_PARTS]),
				indicator: "orange",
			});
			return;
		}

		// Only set fields this form actually has: `custom_additional_number` and
		// `custom_short_address` are ours, `custom_area` and
		// `custom_building_number` are ksa_compliance's, and a site missing any of
		// them must degrade rather than throw inside a form event.
		const present = {};
		Object.keys(values).forEach((fieldname) => {
			if (frm.get_field(fieldname)) {
				present[fieldname] = values[fieldname];
			}
		});
		frm.set_value(present);

		frappe.show_alert({ message: __("National address fields populated"), indicator: "green" });
	},
});
