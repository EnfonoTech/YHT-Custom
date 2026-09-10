# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""What a transaction list opens on, before anyone touches a filter.

Client sheet item 35: the eight fiscal-year lists should open on the CURRENT
year rather than on everything ever imported.

**Mechanism**, verified in
`frappe/public/js/frappe/list/list_view.js::setup_defaults`:

    if (this.view_user_settings.filters && this.view_user_settings.filters.length) {
        this.filters = this.validate_filters(saved_filters);   // 1: the user's own
    } else {
        this.filters = (this.settings.filters || []).map(...); // 2: listview_settings
    }

So `frappe.listview_settings[dt].filters` is the supported pre-set, and the
user's own saved filters always win over it.

🔴 THIS IS A FILTER DEFAULT, NEVER A FIELD DEFAULT. `custom_fiscal_year` stays
`read_only` with no `default` of any kind — a fixed default on the FIELD is what
left 731 Sales Invoices stamped FY 2026 while dated from 2024-08-01 on the
client's previous system. `fiscal_year.set_fiscal_year` computes the stored
value from the posting date on every save and that does not change here.

`setup_defaults()` runs synchronously while the list is being built, so the year
has to be in the boot payload before the list exists — hence
`boot.boot_session` rather than a call from the list JS. Bootinfo is cached per
user, so a session held open across a year-end keeps the old value until the
cache clears; `bench clear-cache` is already in the deploy sequence.
"""

from frappe.utils import today

from yht_custom import fiscal_year


def current_fiscal_year() -> str:
	"""The Fiscal Year covering today, or `""` when none does.

	Reuses `fiscal_year.resolve`, which is what makes this roll into 2027 on its
	own and inherits the standing rule that a fiscal-year lookup must never be
	the reason something fails: no year covering today gives an empty string, and
	the list JS then sets no filter at all.
	"""
	return fiscal_year.resolve(today())
