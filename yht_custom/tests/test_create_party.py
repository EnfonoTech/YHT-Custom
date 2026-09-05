# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

"""Create New Customer / Supplier — the rmax_custom dialog, ported.

These tests WRITE. FrappeTestCase wraps each in a transaction and rolls it back,
which is the only reason that is acceptable against a live client site.

The cases worth having are the ones the port could plausibly have got wrong:
where the mobile number ends up, which VAT field is written, and whether a rule
that the dialog enforces also holds on the server.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from yht_custom.api import customer as customer_api
from yht_custom.api import supplier as supplier_api

VAT = "399999999900001"
#: Suppliers keep their own, so a customer test cannot poison a supplier one.
SUPPLIER_VAT = "399999999900003"
VAT_TWO = "399999999900002"


def _address(**overrides):
    return {
        "address_line1": "King Fahd Road",
        "custom_building_number": "1234",
        "custom_area": "Al Aqrabiyah",
        "city": "Al Khobar",
        "pincode": "34421",
        "country": "Saudi Arabia",
        **overrides,
    }


class TestCreateCustomer(FrappeTestCase):
    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def test_b2c_is_an_individual_and_asks_for_nothing_else(self):
        out = customer_api.create_customer_with_address(
            customer_name="_ZZ B2C Customer",
            buyer_kind="B2C (Individual)",
            mobile_no="0500000000",
        )
        doc = frappe.get_doc("Customer", out["customer"])
        self.assertEqual(doc.customer_type, "Individual")
        self.assertFalse(doc.custom_vat_registration_number)
        self.assertIsNone(out["address"])

    def test_the_mobile_number_lands_on_the_contact(self):
        """🔴 THE ADAPTATION THAT WOULD HAVE FAILED SILENTLY.

        rmax writes `customer.mobile_no` directly. On khobhar that field is READ
        ONLY — erpnext derives it from the primary Contact — so the write is
        accepted, persists nothing, and leaves a customer nobody can phone. It is
        editable on yht-test, which is exactly why this asserts the CONTACT rather
        than the field: the detour has to be right on both.
        """
        out = customer_api.create_customer_with_address(
            customer_name="_ZZ Contact Customer",
            buyer_kind="B2C (Individual)",
            mobile_no="0500000001",
        )
        self.assertTrue(out["contact"], "no Contact was created, so the mobile went nowhere")
        contact = frappe.get_doc("Contact", out["contact"])
        self.assertEqual(contact.phone_nos[0].phone, "0500000001")

    def test_b2b_writes_both_vat_fields(self):
        """ksa_compliance reads the custom field; the rest of erpnext reads tax_id."""
        out = customer_api.create_customer_with_address(
            customer_name="_ZZ B2B Customer",
            buyer_kind="B2B (Company)",
            mobile_no="0500000000",
            custom_vat_registration_number=VAT,
            **_address(),
        )
        doc = frappe.get_doc("Customer", out["customer"])
        self.assertEqual(doc.customer_type, "Company")
        self.assertEqual(doc.custom_vat_registration_number, VAT)
        self.assertEqual(doc.tax_id, VAT)
        self.assertTrue(out["address"])

    def test_a_short_mobile_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            customer_api.create_customer_with_address(
                customer_name="_ZZ Short Mobile", buyer_kind="B2C (Individual)", mobile_no="12345"
            )

    def test_a_vat_that_is_not_fifteen_digits_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            customer_api.create_customer_with_address(
                customer_name="_ZZ Bad VAT",
                buyer_kind="B2B (Company)",
                mobile_no="0500000000",
                custom_vat_registration_number="12345",
                **_address(),
            )

    def test_b2b_without_a_district_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            customer_api.create_customer_with_address(
                customer_name="_ZZ No District",
                buyer_kind="B2B (Company)",
                mobile_no="0500000000",
                custom_vat_registration_number=VAT,
                **_address(custom_area=""),
            )

    def test_a_duplicate_vat_is_refused(self):
        customer_api.create_customer_with_address(
            customer_name="_ZZ VAT Holder",
            buyer_kind="B2B (Company)",
            mobile_no="0500000000",
            custom_vat_registration_number=VAT_TWO,
            **_address(),
        )
        with self.assertRaises(frappe.ValidationError):
            customer_api.create_customer_with_address(
                customer_name="_ZZ VAT Copycat",
                buyer_kind="B2B (Company)",
                mobile_no="0500000000",
                custom_vat_registration_number=VAT_TWO,
                **_address(),
            )

    def test_a_manager_may_allow_a_duplicate_with_a_reason(self):
        customer_api.create_customer_with_address(
            customer_name="_ZZ VAT Holder 2",
            buyer_kind="B2B (Company)",
            mobile_no="0500000000",
            custom_vat_registration_number=VAT_TWO,
            **_address(),
        )
        out = customer_api.create_customer_with_address(
            customer_name="_ZZ VAT Override",
            buyer_kind="B2B (Company)",
            mobile_no="0500000000",
            custom_vat_registration_number=VAT_TWO,
            allow_duplicate_vat=1,
            duplicate_vat_reason="Branch of the same group",
            **_address(),
        )
        doc = frappe.get_doc("Customer", out["customer"])
        self.assertTrue(doc.custom_allow_duplicate_vat)
        self.assertEqual(doc.custom_duplicate_vat_reason, "Branch of the same group")

    def test_an_override_without_a_reason_is_refused(self):
        """The override is only auditable if it carries a name for the decision."""
        with self.assertRaises(frappe.ValidationError):
            customer_api.create_customer_with_address(
                customer_name="_ZZ Silent Override",
                buyer_kind="B2B (Company)",
                mobile_no="0500000000",
                custom_vat_registration_number=VAT,
                allow_duplicate_vat=1,
                **_address(),
            )

    def test_the_rule_also_holds_when_the_form_is_edited_directly(self):
        """Otherwise the Customer form itself is the way around the dialog."""
        doc = frappe.new_doc("Customer")
        doc.customer_name = "_ZZ Direct Edit"
        doc.customer_type = "Company"
        doc.customer_group = customer_api.party.default_group("Customer")
        doc.territory = customer_api.party.default_territory()
        doc.custom_vat_registration_number = "123"
        with self.assertRaises(frappe.ValidationError):
            doc.insert()

    def test_defaults_tell_the_dialog_what_it_needs(self):
        d = customer_api.get_customer_defaults()
        self.assertEqual(d["vat_length"], 15)
        self.assertIn("can_override_vat", d)
        self.assertIn("can_create", d)


class TestCreateSupplier(FrappeTestCase):
    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def test_b2c_supplier_is_an_individual(self):
        out = supplier_api.create_supplier_with_address(
            supplier_name="_ZZ B2C Supplier",
            buyer_kind="B2C (Individual)",
            mobile_no="0500000000",
        )
        doc = frappe.get_doc("Supplier", out["supplier"])
        self.assertEqual(doc.supplier_type, "Individual")
        self.assertFalse(doc.tax_id)

    def test_b2b_supplier_uses_the_core_tax_id(self):
        """There is no custom_vat_registration_number on Supplier here."""
        self.assertIsNone(frappe.get_meta("Supplier").get_field("custom_vat_registration_number"))
        out = supplier_api.create_supplier_with_address(
            supplier_name="_ZZ B2B Supplier",
            buyer_kind="B2B (Company)",
            mobile_no="0500000000",
            tax_id=SUPPLIER_VAT,
            **_address(),
        )
        doc = frappe.get_doc("Supplier", out["supplier"])
        self.assertEqual(doc.supplier_type, "Company")
        self.assertEqual(doc.tax_id, SUPPLIER_VAT)

    def test_b2b_supplier_without_an_address_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            supplier_api.create_supplier_with_address(
                supplier_name="_ZZ Supplier No Address",
                buyer_kind="B2B (Company)",
                mobile_no="0500000000",
                tax_id=SUPPLIER_VAT,
            )


class TestPortWiring(FrappeTestCase):
    """The dialog is useless if the form never loads it."""

    def _hooks(self):
        with open(frappe.get_app_path("yht_custom", "hooks.py"), encoding="utf-8") as handle:
            return handle.read()

    def test_the_customer_dialog_is_registered_where_a_customer_is_chosen(self):
        from yht_custom import hooks

        for doctype in ("Sales Invoice", "Quotation"):
            entry = hooks.doctype_js[doctype]
            entry = entry if isinstance(entry, list) else [entry]
            self.assertIn("public/js/create_customer.js", entry, doctype)

    def test_the_supplier_dialog_is_registered_on_the_buying_forms(self):
        from yht_custom import hooks

        for doctype in ("Purchase Invoice", "Purchase Order", "Purchase Receipt"):
            entry = hooks.doctype_js[doctype]
            entry = entry if isinstance(entry, list) else [entry]
            self.assertIn("public/js/create_supplier.js", entry, doctype)

    def test_the_replaced_dialog_is_gone(self):
        """simple_party.js was replaced, not left alongside to drift."""
        self.assertNotIn("simple_party", self._hooks())

    def test_the_vat_rule_is_wired_on_both_parties(self):
        from yht_custom import hooks

        self.assertEqual(
            hooks.doc_events["Customer"]["validate"],
            "yht_custom.api.customer.enforce_vat_duplicate_rule",
        )
        self.assertEqual(
            hooks.doc_events["Supplier"]["validate"],
            "yht_custom.api.supplier.enforce_vat_duplicate_rule",
        )

    def test_the_override_fields_are_provisioned(self):
        for doctype in ("Customer", "Supplier"):
            meta = frappe.get_meta(doctype)
            self.assertTrue(meta.get_field("custom_allow_duplicate_vat"), doctype)
            self.assertTrue(meta.get_field("custom_duplicate_vat_reason"), doctype)
