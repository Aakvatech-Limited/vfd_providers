# Copyright (c) 2026, Aakvatech Limited and Contributors
# See license.txt

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_datetime, now_datetime

from vfd_providers.utils.utils import (
    VFD_PROVIDER_HANDLERS,
    get_settings_info,
    posting_all_vfd_invoices,
)
from vfd_providers.vfd_providers.doctype.dirm_vfd_settings.dirm_vfd_settings import (
    get_payload,
    get_provider,
    post_fiscal_receipt,
    send_dirm_vfd_request,
)

SESSION_RESPONSE = {
    "status": 200,
    "statusDesc": "success",
    "data": {
        "userStatus": "Active",
        "token": "fdfgsfww4fassddbbtym6765d4",
        "tokenType": "bearer",
        "expiresIn": 86400,
    },
}

RECEIPT_RESPONSE = {
    "status": 200,
    "statusDesc": "success",
    "data": {
        "dateTime": "2026-09-08 13:13:14",
        "rctNum": 2,
        "zNum": 20260908,
        "traReceiptVerificationCode": "530809122_131314",
        "traReceiptVerificationUrl": "www.dirmgroup.co.tz/530809122_131314",
    },
}

test_ignore = ["Company", "Cost Center"]


def get_response(body, status_code=200, ok=True):
    return SimpleNamespace(ok=ok, status_code=status_code, text=json.dumps(body))


def get_test_company():
    """The company both the settings and the test invoices belong to."""
    return frappe.defaults.get_user_default("Company") or frappe.db.get_value(
        "Company", {}, "name"
    )


class TestDIRMVFDSettings(FrappeTestCase):
    def setUp(self):
        self.company = get_test_company()
        self.settings = self.get_settings()
        # Pin the environment so the URL assertions do not depend on site setup.
        self.provider = self.get_provider_record()
        self.provider.sandbox = 1
        self.provider.save()

    def get_provider_record(self):
        """A provider record under a name of the user's choosing, as in real use."""
        name = frappe.db.get_value(
            "VFD Provider", {"vfd_provider_settings": "DIRM VFD Settings"}
        )
        if name:
            return frappe.get_doc("VFD Provider", name)

        return frappe.get_doc(
            {
                "doctype": "VFD Provider",
                "vfd_provider": f"DIRM VFD {frappe.generate_hash(length=6)}",
                "vfd_provider_settings": "DIRM VFD Settings",
                "sandbox": 1,
            }
        ).insert()

    def get_settings(self):
        if frappe.db.exists("DIRM VFD Settings", self.company):
            return frappe.get_doc("DIRM VFD Settings", self.company)

        return frappe.get_doc(
            {
                "doctype": "DIRM VFD Settings",
                "company": self.company,
                "email": "admin@example.com",
                "password": "secret",
                "vfd_start_date": "2026-01-01",
            }
        ).insert()

    def test_token_is_invalid_when_missing(self):
        self.settings.token = None
        self.settings.token_expires = None
        self.assertFalse(self.settings.is_token_valid)

    def test_token_is_invalid_close_to_expiry(self):
        self.settings.token = "token"
        self.settings.token_expires = add_to_date(now_datetime(), minutes=10)
        self.assertFalse(self.settings.is_token_valid)

    def test_token_is_valid_well_before_expiry(self):
        self.settings.token = "token"
        self.settings.token_expires = add_to_date(now_datetime(), days=1)
        self.assertTrue(self.settings.is_token_valid)

    def test_get_session_token_stores_token_and_expiry(self):
        with patch("requests.request", return_value=get_response(SESSION_RESPONSE)):
            self.settings.get_session_token()

        self.assertEqual(
            self.settings.get_password("token"), "fdfgsfww4fassddbbtym6765d4"
        )
        self.assertEqual(self.settings.token_type, "bearer")
        self.assertAlmostEqual(
            get_datetime(self.settings.token_expires).timestamp(),
            add_to_date(now_datetime(), seconds=86400).timestamp(),
            delta=60,
        )
        self.assertTrue(self.settings.is_token_valid)

    def test_get_session_token_throws_when_credentials_are_rejected(self):
        rejected = {
            "status": 203,
            "statusDesc": "Invalid login credentials",
            "data": {},
        }

        with patch("requests.request", return_value=get_response(rejected)):
            self.assertRaises(frappe.ValidationError, self.settings.get_session_token)

    def test_get_session_token_needs_credentials(self):
        self.settings.email = None
        self.assertRaises(frappe.ValidationError, self.settings.get_session_token)

    def test_session_request_hits_the_sandbox_url_without_authorization(self):
        with patch(
            "requests.request", return_value=get_response(SESSION_RESPONSE)
        ) as request:
            send_dirm_vfd_request("get_token", self.settings, "{}")

        self.assertEqual(
            request.call_args.kwargs["url"],
            "https://dirmvfd.co.tz/api_demo/api/v1/session/get_token",
        )
        self.assertNotIn("Authorization", request.call_args.kwargs["headers"])

    def test_receipt_request_carries_the_bearer_token(self):
        with patch("requests.request", return_value=get_response(SESSION_RESPONSE)):
            self.settings.get_session_token()

        with patch("requests.request", return_value=get_response({})) as request:
            send_dirm_vfd_request("post_receipt", self.settings, "{}")

        self.assertEqual(
            request.call_args.kwargs["url"],
            "https://dirmvfd.co.tz/api_demo/api/v1/receipts/post",
        )
        self.assertEqual(
            request.call_args.kwargs["headers"]["Authorization"],
            "Bearer fdfgsfww4fassddbbtym6765d4",
        )

    def test_unknown_endpoint_throws(self):
        self.assertRaises(
            frappe.ValidationError, self.provider.get_endpoint, "z_report"
        )

    def test_endpoints_are_filled_in_on_insert(self):
        self.assertEqual(
            self.provider.get_endpoint("get_token"), "/api/v1/session/get_token"
        )
        self.assertEqual(
            self.provider.get_endpoint("post_receipt"), "/api/v1/receipts/post"
        )

    def test_post_fiscal_receipt_needs_an_invoice(self):
        self.assertRaises(frappe.ValidationError, post_fiscal_receipt)

    def test_handlers_are_keyed_by_settings_doctype(self):
        get_payload, post_receipt = VFD_PROVIDER_HANDLERS["DIRM VFD Settings"]

        self.assertEqual(post_receipt, post_fiscal_receipt)
        self.assertEqual(get_payload.__name__, "get_payload")

    def test_missing_settings_row_is_reported_clearly(self):
        invoice = frappe._dict(
            {"company": "No Such Company", "posting_date": "2026-01-02"}
        )

        self.assertRaises(
            frappe.ValidationError, get_settings_info, invoice, "DIRM VFD Settings"
        )

    def test_batch_job_posts_an_invoice_that_was_never_sent(self):
        # vfd_status defaults to "Not Sent", which is the whole point of the job:
        # the user submitted the invoice without auto generation.
        invoice = self.get_submitted_invoice()
        self.assertEqual(invoice.vfd_status, "Not Sent")

        frappe.get_doc(
            {
                "doctype": "Company VFD Provider",
                "company": self.company,
                "vfd_provider": self.provider.name,
            }
        ).insert(ignore_if_duplicate=True)
        frappe.db.set_value(
            "DIRM VFD Settings", self.company, "vfd_start_date", invoice.posting_date
        )
        frappe.clear_cache(doctype="DIRM VFD Settings")

        with patch("requests.request", side_effect=self.answer_dirm):
            posting_all_vfd_invoices()

        self.assertEqual(
            frappe.db.get_value("Sales Invoice", invoice.name, "vfd_status"), "Success"
        )

    def answer_dirm(self, **kwargs):
        body = SESSION_RESPONSE if "get_token" in kwargs["url"] else RECEIPT_RESPONSE
        return get_response(body)

    def get_submitted_invoice(self):
        """A submitted VFD invoice, satisfying the app's own before_submit checks."""
        vat_account = frappe.db.get_value(
            "Account",
            {"company": self.company, "is_group": 0, "root_type": "Liability"},
            "name",
        )
        tax_template = frappe.get_doc(
            {
                "doctype": "Item Tax Template",
                "title": f"VFD Test Tax {frappe.generate_hash(length=6)}",
                "company": self.company,
                "taxes": [{"tax_type": vat_account, "tax_rate": 18}],
            }
        ).insert()
        frappe.db.set_value(
            "Item Tax Template",
            tax_template.name,
            "vfd_taxcode",
            "1- Standard Rate (18%)",
        )
        item = frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": f"VFD Test Item {frappe.generate_hash(length=6)}",
                "item_group": frappe.db.get_value(
                    "Item Group", {"is_group": 0}, "name"
                ),
                "stock_uom": "Nos",
                "is_stock_item": 0,
            }
        ).insert()
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": f"VFD Test Customer {frappe.generate_hash(length=6)}",
                "customer_group": frappe.db.get_value(
                    "Customer Group", {"is_group": 0}, "name"
                ),
                "territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
            }
        ).insert()
        cost_center = frappe.db.get_value(
            "Cost Center", {"company": self.company, "is_group": 0}, "name"
        )
        invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "company": self.company,
                "customer": customer.name,
                "currency": frappe.db.get_value(
                    "Company", self.company, "default_currency"
                ),
                "items": [
                    {
                        "item_code": item.name,
                        "qty": 1,
                        "rate": 100000,
                        "item_tax_template": tax_template.name,
                        "income_account": frappe.db.get_value(
                            "Account",
                            {
                                "company": self.company,
                                "is_group": 0,
                                "root_type": "Income",
                            },
                            "name",
                        ),
                        "cost_center": cost_center,
                    }
                ],
                "taxes": [
                    {
                        "charge_type": "On Net Total",
                        "account_head": vat_account,
                        "rate": 18,
                        "description": "VAT",
                        "cost_center": cost_center,
                    }
                ],
            }
        ).insert()
        invoice.submit()
        invoice.reload()
        return invoice

    def test_provider_is_resolved_by_settings_doctype_not_by_name(self):
        # The record is named freely, so posting must not rely on its name.
        self.assertEqual(get_provider().name, self.provider.name)

    def test_sandbox_flag_switches_the_stored_base_url(self):
        self.assertEqual(self.provider.base_url, "https://dirmvfd.co.tz/api_demo")

        self.provider.sandbox = 0
        self.provider.save()
        self.assertEqual(self.provider.base_url, "https://dirmvfd.co.tz/api_live")


TAX_CODES = {"Standard Template": 1, "Exempt Template": 5}


def get_item(item_code, base_net_amount, qty=1, item_tax_template="Standard Template"):
    return {
        "item_code": item_code,
        "item_name": item_code,
        "qty": qty,
        "base_net_amount": base_net_amount,
        "base_amount": base_net_amount,
        "item_tax_template": item_tax_template,
    }


def get_invoice(items, payments=None, **values):
    """Unsaved Sales Invoice, enough to build a payload from."""
    invoice = frappe.new_doc("Sales Invoice")
    invoice.name = "SINV-TEST-0001"
    invoice.update(
        {
            "company": get_test_company(),
            "customer": "Example Customer",
            "customer_name": "Example Customer",
            "tax_id": "109445991",
            "vfd_cust_id_type": "6- Other",
            "vfd_cust_id": "",
            "contact_mobile": "+255 655 809 965",
        }
    )
    invoice.update(values)

    for item in items:
        invoice.append("items", item)

    for payment in payments or []:
        invoice.append("payments", payment)

    return invoice


class TestDIRMVFDPayload(FrappeTestCase):
    def setUp(self):
        taxcode_patch = patch(
            "vfd_providers.vfd_providers.doctype.dirm_vfd_settings.dirm_vfd_settings.get_item_taxcode",
            side_effect=lambda template, *args: TAX_CODES[template],
        )
        taxcode_patch.start()
        self.addCleanup(taxcode_patch.stop)
        self.set_vat_registered(1)

    def set_vat_registered(self, value):
        company = get_test_company()
        if not frappe.db.exists("DIRM VFD Settings", company):
            frappe.get_doc(
                {
                    "doctype": "DIRM VFD Settings",
                    "company": company,
                    "email": "admin@example.com",
                    "password": "secret",
                    "vfd_start_date": "2026-01-01",
                }
            ).insert()

        frappe.db.set_value("DIRM VFD Settings", company, "is_vat_registered", value)
        frappe.clear_cache(doctype="DIRM VFD Settings")
        return company

    def test_standard_rate_item_amount_includes_vat(self):
        payload = get_payload(get_invoice([get_item("ITEM-A", 100000)]))

        self.assertEqual(payload["items"][0]["taxCode"], "A")
        self.assertEqual(payload["items"][0]["amt"], 118000.0)
        self.assertEqual(payload["totals"]["totalTaxIncl"], 118000.0)
        self.assertEqual(payload["totals"]["totalTax"], 18000.0)
        self.assertEqual(payload["totals"]["totalTaxExcl"], 100000.0)

    def test_amount_is_the_whole_line_not_a_unit_price(self):
        payload = get_payload(get_invoice([get_item("ITEM-A", 200000, qty=4)]))

        self.assertEqual(payload["items"][0]["qty"], 4)
        self.assertEqual(payload["items"][0]["amt"], 236000.0)
        self.assertEqual(payload["totals"]["totalTaxIncl"], 236000.0)

    def test_totals_match_the_invoice_net_amount_exactly(self):
        # A net amount that does not divide evenly by qty must not drift.
        payload = get_payload(get_invoice([get_item("ITEM-A", 100000, qty=3)]))

        self.assertEqual(payload["totals"]["totalTaxExcl"], 100000.0)
        self.assertEqual(payload["totals"]["totalTax"], 18000.0)
        self.assertEqual(payload["totals"]["totalTaxIncl"], 118000.0)
        self.assertEqual(payload["items"][0]["amt"], 118000.0)

    def test_exempt_item_carries_no_tax(self):
        payload = get_payload(
            get_invoice(
                [get_item("ITEM-E", 300000, item_tax_template="Exempt Template")]
            )
        )

        self.assertEqual(payload["items"][0]["taxCode"], "E")
        self.assertEqual(payload["totals"]["totalTax"], 0.0)
        self.assertEqual(payload["totals"]["totalTaxIncl"], 300000.0)
        self.assertEqual(
            payload["vatTotals"],
            [{"vatRate": "E", "nettAmount": 300000.0, "taxAmount": 0.0}],
        )

    def test_vat_totals_are_grouped_per_tax_code(self):
        payload = get_payload(
            get_invoice(
                [
                    get_item("ITEM-A", 100000),
                    get_item("ITEM-B", 50000),
                    get_item("ITEM-E", 300000, item_tax_template="Exempt Template"),
                ]
            )
        )

        self.assertEqual(
            payload["vatTotals"],
            [
                {"vatRate": "A", "nettAmount": 150000.0, "taxAmount": 27000.0},
                {"vatRate": "E", "nettAmount": 300000.0, "taxAmount": 0.0},
            ],
        )

    def test_vat_totals_match_receipt_totals(self):
        payload = get_payload(
            get_invoice(
                [
                    get_item("ITEM-A", 100000),
                    get_item("ITEM-E", 300000, item_tax_template="Exempt Template"),
                ]
            )
        )

        nett = sum(row["nettAmount"] for row in payload["vatTotals"])
        tax = sum(row["taxAmount"] for row in payload["vatTotals"])
        self.assertEqual(nett, payload["totals"]["totalTaxExcl"])
        self.assertEqual(tax, payload["totals"]["totalTax"])
        self.assertEqual(nett + tax, payload["totals"]["totalTaxIncl"])

    def test_unpaid_invoice_is_billed_as_one_cash_payment(self):
        payload = get_payload(get_invoice([get_item("ITEM-A", 100000)]))

        # DIRM VFD reads payments as a single record, not a list, and rejects
        # the TRA value INVOICE.
        self.assertEqual(
            payload["payments"], {"pmtType": "CASH", "pmtAmount": 118000.0}
        )

    def test_payments_use_the_mode_of_payment_vfd_type(self):
        mode_of_payment = frappe.get_doc(
            {
                "doctype": "Mode of Payment",
                "mode_of_payment": f"Example VFD Cash {frappe.generate_hash(length=6)}",
                "vfd_pmttype": "CASH",
            }
        ).insert()

        payload = get_payload(
            get_invoice(
                [get_item("ITEM-A", 100000)],
                payments=[
                    {"mode_of_payment": mode_of_payment.name, "base_amount": 118000}
                ],
            )
        )

        self.assertEqual(
            payload["payments"], {"pmtType": "CASH", "pmtAmount": 118000.0}
        )

    def test_mode_of_payment_without_vfd_type_throws(self):
        mode_of_payment = frappe.get_doc(
            {
                "doctype": "Mode of Payment",
                "mode_of_payment": f"Example VFD Untyped {frappe.generate_hash(length=6)}",
            }
        ).insert()

        invoice = get_invoice(
            [get_item("ITEM-A", 100000)],
            payments=[{"mode_of_payment": mode_of_payment.name, "base_amount": 118000}],
        )

        self.assertRaises(frappe.ValidationError, get_payload, invoice)

    def test_tendered_amount_and_change_do_not_reach_the_receipt(self):
        mode_of_payment = frappe.get_doc(
            {
                "doctype": "Mode of Payment",
                "mode_of_payment": f"Example VFD Tendered {frappe.generate_hash(length=6)}",
                "vfd_pmttype": "CASH",
            }
        ).insert()

        payload = get_payload(
            get_invoice(
                [get_item("ITEM-A", 100000)],
                payments=[
                    {"mode_of_payment": mode_of_payment.name, "base_amount": 120000}
                ],
                base_change_amount=2000,
            )
        )

        self.assertEqual(
            payload["payments"], {"pmtType": "CASH", "pmtAmount": 118000.0}
        )

    def test_customer_id_type_stored_as_number_is_accepted(self):
        payload = get_payload(
            get_invoice([get_item("ITEM-A", 100000)], vfd_cust_id_type=6)
        )

        self.assertEqual(payload["custIdType"], 6)

    def test_customer_without_identification_sends_empty_id(self):
        payload = get_payload(get_invoice([get_item("ITEM-A", 100000)]))

        self.assertEqual(payload["custIdType"], 6)
        self.assertEqual(payload["custId"], "")

    def test_customer_identification_is_taken_from_the_invoice(self):
        payload = get_payload(
            get_invoice(
                [get_item("ITEM-A", 100000)],
                vfd_cust_id_type="1- TIN",
                vfd_cust_id="109445991",
            )
        )

        self.assertEqual(payload["custIdType"], 1)
        self.assertEqual(payload["custId"], "109445991")

    def test_unique_id_is_the_invoice_name(self):
        invoice = get_invoice([get_item("ITEM-A", 100000)])
        payload = get_payload(invoice)

        self.assertEqual(payload["unique_id"], invoice.name)

    def test_mobile_number_keeps_digits_only(self):
        payload = get_payload(get_invoice([get_item("ITEM-A", 100000)]))

        self.assertEqual(payload["mobileNum"], "255655809965")

    def test_largest_tender_names_the_payment_type(self):
        cash = frappe.get_doc(
            {
                "doctype": "Mode of Payment",
                "mode_of_payment": f"Example VFD Small {frappe.generate_hash(length=6)}",
                "vfd_pmttype": "CASH",
            }
        ).insert()
        card = frappe.get_doc(
            {
                "doctype": "Mode of Payment",
                "mode_of_payment": f"Example VFD Large {frappe.generate_hash(length=6)}",
                "vfd_pmttype": "CCARD",
            }
        ).insert()

        payload = get_payload(
            get_invoice(
                [get_item("ITEM-A", 100000)],
                payments=[
                    {"mode_of_payment": cash.name, "base_amount": 18000},
                    {"mode_of_payment": card.name, "base_amount": 100000},
                ],
            )
        )

        self.assertEqual(
            payload["payments"], {"pmtType": "CCARD", "pmtAmount": 118000.0}
        )

    def test_customer_name_is_cut_to_the_dirm_limit(self):
        payload = get_payload(
            get_invoice(
                [get_item("ITEM-A", 100000)],
                customer_name="GROUPAGE LOGISTICS SERVICES (T) LTD",
            )
        )

        self.assertEqual(payload["custName"], "GROUPAGE LOGISTICS SERVICES T")
        self.assertLessEqual(len(payload["custName"]), 30)

    def test_invoice_payment_type_is_replaced_because_dirm_rejects_it(self):
        mode_of_payment = frappe.get_doc(
            {
                "doctype": "Mode of Payment",
                "mode_of_payment": f"Example VFD Credit {frappe.generate_hash(length=6)}",
                "vfd_pmttype": "INVOICE",
            }
        ).insert()

        payload = get_payload(
            get_invoice(
                [get_item("ITEM-A", 100000)],
                payments=[
                    {"mode_of_payment": mode_of_payment.name, "base_amount": 118000}
                ],
            )
        )

        self.assertEqual(payload["payments"]["pmtType"], "CASH")

    def test_account_without_vat_registration_declares_no_tax(self):
        # TRA holds some DIRM accounts as not VAT registered; the receipt then
        # carries the charged amount and no tax at all.
        self.set_vat_registered(0)
        payload = get_payload(get_invoice([get_item("ITEM-A", 100000)]))

        charged = payload["items"][0]["amt"]
        self.assertEqual(charged, 118000.0)
        self.assertEqual(payload["totals"]["totalTax"], 0.0)
        self.assertEqual(payload["totals"]["totalTaxExcl"], charged)
        self.assertEqual(payload["totals"]["totalTaxIncl"], charged)
        self.assertEqual(payload["payments"]["pmtAmount"], charged)
        self.assertEqual(
            payload["vatTotals"],
            [{"vatRate": "A", "nettAmount": charged, "taxAmount": 0.0}],
        )
