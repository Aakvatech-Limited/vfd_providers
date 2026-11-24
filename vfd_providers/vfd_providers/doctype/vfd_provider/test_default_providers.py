from unittest.mock import Mock, patch

from frappe.tests.utils import FrappeTestCase

from vfd_providers.patches import register_default_providers


class TestDefaultProviders(FrappeTestCase):
    def test_creates_documented_defaults_and_preserves_existing(self):
        existing = set()
        records = []

        def exists(doctype, filters):
            self.assertEqual(doctype, "VFD Provider")
            return filters["vfd_provider"] in existing

        def get_doc(data):
            doc = Mock()

            def insert(**kwargs):
                self.assertTrue(kwargs["ignore_permissions"])
                records.append(data)
                existing.add(data["vfd_provider"])

            doc.insert.side_effect = insert
            return doc

        with (
            patch.object(register_default_providers.frappe.db, "exists", side_effect=exists),
            patch.object(register_default_providers.frappe, "get_doc", side_effect=get_doc),
            patch.object(register_default_providers, "register_pergamon") as pergamon,
        ):
            register_default_providers.execute()
            register_default_providers.execute()
            self.assertEqual(pergamon.call_count, 2)

        self.assertEqual(len(records), 3)
        by_name = {row["vfd_provider"]: row for row in records}
        self.assertEqual(by_name["TotalVFD"]["base_url"], "https://api.totalvfd.co.tz")
        self.assertEqual(by_name["TotalVFD"]["attributes"], [{"key": "sales", "value": "/sales"}])
        self.assertEqual(len(by_name["VFDPlus"]["attributes"]), 4)
        self.assertEqual(len(by_name["SimplifyVFD"]["attributes"]), 3)
        for row in records:
            self.assertEqual(set(row), {
                "doctype", "vfd_provider", "vfd_provider_settings",
                "vfd_provider_controller", "base_url", "attributes",
            })
