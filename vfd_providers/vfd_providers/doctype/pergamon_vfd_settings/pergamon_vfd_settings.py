"""Pergamon VFD adapter for the documented /api/v1/invoices endpoint.

The supplied API collection does not document response examples. Never
interpret an HTTP success alone as a fiscal receipt confirmation.
"""
import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlparse

import frappe
import requests
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate, nowtime

from vfd_providers.vfd_providers.utils import get_vat_amount

TAX_CODES = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"}
CUSTOMER_ID_TYPES = {"1", "2", "3", "4", "5", "6"}


class PergamonVFDSettings(Document):
    def validate(self):
        parsed = urlparse(self.api_url or "")
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            frappe.throw(_("Pergamon API URL must be an HTTPS base URL without credentials or query parameters."))


def _money(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def get_payload(doc):
    """Map the Sales Invoice to the Pergamon Generate Receipt JSON sample."""
    if doc.docstatus != 1 or doc.is_return or doc.is_not_vfd_invoice:
        frappe.throw(_("Only submitted, non-return VFD Sales Invoices can be sent."))
    if doc.currency != "TZS":
        # Currency conversion for the documented API has not been verified.
        frappe.throw(_("Pergamon requires confirmed foreign-currency behavior before non-TZS invoices may be sent."))
    items = []
    for item in doc.items:
        if not item.qty or item.qty <= 0:
            frappe.throw(_("Pergamon requires a positive item quantity."))
        tax_template = item.item_tax_template
        code = frappe.get_cached_value("Item Tax Template", tax_template, "vfd_taxcode") if tax_template else None
        code = str(code or "")[:1]
        if code not in TAX_CODES:
            frappe.throw(_("Configure a valid VFD tax code on each Item Tax Template."))
        line_total = _money(get_vat_amount(item, code, precision=2))
        unit_price = _money(Decimal(str(line_total)) / Decimal(str(item.qty)))
        items.append({
            "name": item.item_name or item.item_code,
            "qty": float(item.qty),
            "unitPrice": unit_price,
            "amount": line_total,
            "discount": 0,
            "taxCode": TAX_CODES[code],
        })
    if not items:
        frappe.throw(_("Pergamon receipt requires at least one item."))

    total = _money(sum(Decimal(str(item["amount"])) for item in items))
    if abs(Decimal(str(total)) - Decimal(str(doc.grand_total))) > Decimal("0.05"):
        frappe.throw(_("Pergamon item total does not reconcile to Sales Invoice grand total."))

    cust_type = str(doc.vfd_cust_id_type or "6")[:1]
    if cust_type not in CUSTOMER_ID_TYPES:
        frappe.throw(_("Unsupported VFD customer identification type."))
    settings = frappe.get_doc("Pergamon VFD Settings", doc.company)
    return {
        "traderInvoiceNo": doc.name,
        "totalAmount": total,
        "paymentType": settings.payment_type or "INVOICE",
        "custIdType": cust_type,
        "custId": doc.vfd_cust_id or "",
        "custName": doc.customer_name or "",
        "custPhone": frappe.db.get_value("Customer", doc.customer, "mobile_no") or "",
        "currency": "TZS",
        "exchangeRate": 1.0,
        "dateTime": str(doc.posting_date) + " " + str(doc.posting_time or "00:00:00")[:8],
        "salesItems": items,
    }


def _receipt_evidence(response):
    """Unknown response shape: only persist success with explicit fiscal evidence."""
    if not isinstance(response, dict):
        return None
    body = response.get("data") if isinstance(response.get("data"), dict) else response
    if body.get("success") is False or str(body.get("status", "")).lower() in {"failed", "error", "rejected"}:
        return None
    # These aliases are provisional pending a real Pergamon response sample.
    number = body.get("rctvnum") or body.get("verificationCode") or body.get("receiptNumber")
    if not number:
        return None
    return {"number": str(number), "url": body.get("verificationUrl") or body.get("verificationLink") or "", "body": body}


def _api_request(settings, method, path, payload=None):
    url = (settings.api_url or "").rstrip("/") + path
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        frappe.throw(_("Pergamon endpoint must use HTTPS."))
    response = requests.request(
        method, url, json=payload, auth=(settings.username, settings.get_password("password")),
        headers={"Accept": "application/json"}, timeout=(10, 45),
    )
    try:
        data = response.json()
    except ValueError:
        data = {"error": "Non-JSON response"}
    return response.status_code, data


@frappe.whitelist()
def post_fiscal_receipt(doc=None, method="POST", payload=None, invoice_id=None, preview=False):
    if invoice_id:
        doc = frappe.get_doc("Sales Invoice", invoice_id)
    if not doc:
        frappe.throw(_("Sales Invoice is required."))
    if frappe.session.user != "Administrator" and not frappe.has_permission("Sales Invoice", "read", doc=doc):
        frappe.throw(_("Not permitted to read this Sales Invoice."), frappe.PermissionError)
    if doc.docstatus != 1 or doc.is_return or doc.is_not_vfd_invoice:
        frappe.throw(_("Only submitted, eligible invoices can be sent."))
    provider = frappe.db.get_value("Company VFD Provider", doc.company, "vfd_provider")
    if provider != "Pergamon":
        frappe.throw(_("Pergamon is not configured for this company."))
    if doc.vfd_status == "Success":
        return {"data": {"message": "Already submitted"}, "vfd_provider": "Pergamon", "preview": preview}

    settings = frappe.get_doc("Pergamon VFD Settings", doc.company)
    if frappe.utils.getdate(doc.posting_date) < frappe.utils.getdate(settings.vfd_start_date):
        frappe.throw(_("Invoice predates the configured Pergamon VFD start date."))

    # Never trust client-supplied payload as fiscal data.
    body = get_payload(doc)
    previous = frappe.db.get_all(
        "VFD Provider Posting",
        filters={"sales_invoice": doc.name},
        fields=["name", "ackcode", "ackmsg"],
        order_by="creation desc", limit=1,
    )
    if str(doc.vfd_status) == "Pending" or (previous and previous[0].ackcode == 0):
        frappe.throw(_("Previous Pergamon submission is unresolved. Reconcile the invoice using GET /invoices before resending."))

    posting = frappe.new_doc("VFD Provider Posting")
    posting.sales_invoice = doc.name
    posting.date = nowdate()
    posting.time = nowtime()
    posting.req_headers = json.dumps({"Accept": "application/json", "Authorization": "[REDACTED]"})
    posting.req_data = json.dumps(body, ensure_ascii=False)
    posting.ackcode = 0
    posting.ackmsg = "Submission initiated; awaiting Pergamon response"
    posting.insert(ignore_permissions=True)
    frappe.db.set_value("Sales Invoice", doc.name, {"vfd_posting_info": posting.name, "vfd_status": "Pending"}, update_modified=False)
    # The external API can accept a receipt even when its response times out.
    # Commit the intent before any network call so a retry cannot silently double-issue.
    frappe.db.commit()
    try:
        status, response = _api_request(settings, "POST", "/invoices", body)
    except requests.RequestException:
        frappe.log_error(title="Pergamon VFD connection unresolved", message="Reconcile Sales Invoice " + doc.name + " with Pergamon before retry.")
        frappe.throw(_("Pergamon response unavailable. Submission remains Pending; reconcile before retrying."))
    posting.db_set("ackcode", status)
    posting.db_set("ackmsg", json.dumps(response, ensure_ascii=False)[:1000])

    evidence = _receipt_evidence(response) if 200 <= status < 300 else None
    values = {"vfd_posting_info": posting.name, "vfd_status": "Success" if evidence else "Pending"}
    if evidence:
        values.update({"vfd_rctvnum": evidence["number"], "vfd_verification_url": evidence["url"],
                       "vfd_date": posting.date, "vfd_time": posting.time})
    frappe.db.set_value("Sales Invoice", doc.name, values, update_modified=False)
    if not evidence:
        frappe.msgprint(_("Pergamon response is not verified as a fiscal receipt. Invoice is Pending; reconcile before retrying."))
    return {"data": response, "vfd_provider": "Pergamon", "preview": preview, "verified": bool(evidence)}


def get_invoice(company, invoice_id):
    """Read-only reconciliation endpoint; request ID is Pergamon's numeric invoice ID."""
    if not frappe.has_permission("Pergamon VFD Settings", "read"):
        frappe.throw(_("Not permitted."), frappe.PermissionError)
    if not str(invoice_id).isdigit():
        frappe.throw(_("Pergamon invoice ID must be numeric."))
    return _api_request(frappe.get_doc("Pergamon VFD Settings", company), "GET", "/invoices/" + str(invoice_id))


def get_invoices(company):
    if not frappe.has_permission("Pergamon VFD Settings", "read"):
        frappe.throw(_("Not permitted."), frappe.PermissionError)
    return _api_request(frappe.get_doc("Pergamon VFD Settings", company), "GET", "/invoices")
