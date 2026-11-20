"""Unit checks for the Pergamon adapter's non-negotiable boundaries."""
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from vfd_providers.vfd_providers.doctype.pergamon_vfd_settings.pergamon_vfd_settings import (
    _money, _receipt_evidence, get_payload,
)


class TestPergamonVFD(FrappeTestCase):
    def test_amount_half_up_rounding(self):
        self.assertEqual(_money("10.125"), 10.13)

    def test_http_success_without_receipt_is_not_success(self):
        self.assertIsNone(_receipt_evidence({"message": "Accepted"}))
        self.assertIsNone(_receipt_evidence({"success": False, "receiptNumber": "1"}))
        self.assertIsNone(_receipt_evidence({"status": "error", "receiptNumber": "1"}))

    def test_explicit_receipt_evidence(self):
        receipt = _receipt_evidence({"data": {"verificationCode": "ABC12", "verificationUrl": "https://example.com"}})
        self.assertEqual(receipt["number"], "ABC12")

    def test_reject_foreign_currency(self):
        doc = Mock(docstatus=1, is_return=0, is_not_vfd_invoice=0, currency="USD")
        with self.assertRaises(frappe.ValidationError):
            get_payload(doc)

    def test_reject_draft_invoice(self):
        doc = Mock(docstatus=0, is_return=0, is_not_vfd_invoice=0)
        with self.assertRaises(frappe.ValidationError):
            get_payload(doc)
