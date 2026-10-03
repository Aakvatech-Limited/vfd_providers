# Copyright (c) 2023, Aakvatech Limited and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

DIRM_SETTINGS = "DIRM VFD Settings"
DIRM_TEST_URL = "https://dirmvfd.co.tz/api_demo"
DIRM_LIVE_URL = "https://dirmvfd.co.tz/api_live"
MANUAL_URL = "https://vfd.example.com/api"

test_ignore = ["Company", "Cost Center"]


class TestVFDProvider(FrappeTestCase):
    def get_provider(self, **values):
        provider = frappe.new_doc("VFD Provider")
        provider.vfd_provider = f"Example VFD {frappe.generate_hash(length=6)}"
        provider.vfd_provider_settings = DIRM_SETTINGS
        provider.update(values)
        return provider

    def test_sandbox_uses_the_test_url_of_the_selected_provider(self):
        provider = self.get_provider(sandbox=1).insert()
        self.assertEqual(provider.base_url, DIRM_TEST_URL)

    def test_live_url_is_used_when_sandbox_is_off(self):
        provider = self.get_provider(sandbox=0).insert()
        self.assertEqual(provider.base_url, DIRM_LIVE_URL)

    def test_toggling_sandbox_switches_base_url(self):
        provider = self.get_provider(sandbox=0).insert()

        provider.sandbox = 1
        provider.save()
        self.assertEqual(provider.base_url, DIRM_TEST_URL)

        provider.sandbox = 0
        provider.save()
        self.assertEqual(provider.base_url, DIRM_LIVE_URL)

    def test_endpoints_are_added_on_insert(self):
        provider = self.get_provider(sandbox=1).insert()

        self.assertEqual(
            {row.key: row.value for row in provider.attributes},
            {
                "get_token": "/api/v1/session/get_token",
                "post_receipt": "/api/v1/receipts/post",
            },
        )

    def test_an_entered_endpoint_is_not_overwritten(self):
        provider = self.get_provider(sandbox=1)
        provider.append("attributes", {"key": "post_receipt", "value": "/custom/post"})
        provider.insert()

        self.assertEqual(provider.get_endpoint("post_receipt"), "/custom/post")
        self.assertEqual(
            provider.get_endpoint("get_token"), "/api/v1/session/get_token"
        )

    def test_unknown_provider_keeps_the_url_that_was_entered(self):
        provider = self.get_provider(
            vfd_provider_settings="Total VFD Setting", base_url=MANUAL_URL, sandbox=1
        ).insert()

        self.assertEqual(provider.base_url, MANUAL_URL)
        self.assertEqual(provider.attributes, [])

    def test_missing_endpoint_throws(self):
        provider = self.get_provider(sandbox=1).insert()
        self.assertRaises(frappe.ValidationError, provider.get_endpoint, "z_report")
