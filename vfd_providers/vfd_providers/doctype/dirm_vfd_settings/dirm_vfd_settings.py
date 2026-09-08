# Copyright (c) 2026, Aakvatech Limited and contributors
# For license information, please see license.txt

import json
from time import sleep

import frappe
import requests
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    add_to_date,
    cint,
    cstr,
    flt,
    get_datetime,
    now_datetime,
    nowdate,
    nowtime,
)

from vfd_providers.utils.sales_invoice import (
    get_item_taxcode,
    remove_all_except_numbers,
    remove_special_characters,
)
from vfd_providers.vfd_providers.utils import get_vat_amount

SETTINGS_DOCTYPE = "DIRM VFD Settings"
SUCCESS_STATUS = 200
TOKEN_LIFESPAN_SECONDS = 86400
# Renew ahead of expiry so a running posting job never uses a dead token.
TOKEN_RENEWAL_MARGIN_MINUTES = 30
REQUEST_ATTEMPTS = 3
# Connect and read timeouts. DIRM VFD answers in seconds or not at all.
REQUEST_TIMEOUT = (5, 60)
NO_IDENTIFICATION = 6
# DIRM VFD rejects a longer name with "Customer name should not exceed 30 characters".
MAX_CUSTOMER_NAME_LENGTH = 30
# Sent when the invoice does not say how it was paid: it carries no payment rows,
# which is the case for a credit sale and for one settled by a Payment Entry.
DEFAULT_PAYMENT_TYPE = "CASH"
TAX_CODE_MAP = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E"}


class DIRMVFDSettings(Document):
    @property
    def is_token_valid(self):
        return is_token_fresh(self.token, self.token_expires)

    @frappe.whitelist()
    def get_session_token(self):
        """Fetch a session token from DIRM VFD. The token is valid for one day."""
        if not self.email or not self.password:
            frappe.throw(_("Email and Password are required!"))

        payload = json.dumps({"email": self.email, "password": self.get_password()})
        data, _headers, _status_code = send_dirm_vfd_request("get_token", self, payload)

        session = data.get("data") or {}
        token = session.get("token")
        if not token:
            frappe.throw(
                _("DIRM VFD did not return a token: {0}").format(
                    data.get("statusDesc") or data.get("status")
                )
            )

        vfd_information = session.get("vfdInformation") or {}
        expires_in = cint(session.get("expiresIn")) or TOKEN_LIFESPAN_SECONDS
        self.vrn = vfd_information.get("vrn") or ""
        self.is_vat_registered = cint(vfd_information.get("isVatRegistered"))
        self.token = token
        self.token_type = session.get("tokenType") or "bearer"
        self.token_expires = add_to_date(now_datetime(), seconds=expires_in)
        self.save(ignore_permissions=True)

        return True


def get_payload(doc):
    """Build the DIRM VFD receipt payload for a Sales Invoice.

    `amt` is the line amount inclusive of VAT and line discounts are already
    inside it. An account TRA does not hold as VAT registered must declare no
    tax at all, so the receipt then carries the charged amount with zero tax.
    """
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE, doc.company)
    lines = get_lines(doc, settings.is_vat_registered)
    totals = get_totals(lines)
    customer_id_type = cint(cstr(doc.vfd_cust_id_type or NO_IDENTIFICATION)[:1])

    return {
        "custName": get_customer_name(doc),
        "mobileNum": remove_all_except_numbers(doc.get("contact_mobile")),
        "vrn": doc.tax_id or "",
        "custIdType": customer_id_type,
        "custId": doc.vfd_cust_id if customer_id_type != NO_IDENTIFICATION else "",
        "unique_id": doc.name,
        "items": [line.item for line in lines],
        "totals": totals,
        "vatTotals": get_vat_totals(lines),
        "payments": get_payment(doc, totals["totalTaxIncl"]),
    }


def get_lines(doc, is_vat_registered):
    """One record per invoice row: the receipt item plus the net and tax behind it."""
    lines = []

    for item in doc.items:
        tax_code = TAX_CODE_MAP[
            get_item_taxcode(item.item_tax_template, item.item_code, doc.name)
        ]
        gross_amount = flt(get_vat_amount(item, tax_code, precision=2), 2)
        tax_amount = (
            flt(gross_amount - flt(item.base_net_amount, 2), 2)
            if is_vat_registered
            else 0.0
        )

        lines.append(
            frappe._dict(
                {
                    "tax_code": tax_code,
                    "net_amount": flt(gross_amount - tax_amount, 2),
                    "tax_amount": tax_amount,
                    "item": {
                        "id": item.item_code,
                        "desc": remove_special_characters(
                            item.item_name or item.item_code
                        ),
                        "qty": item.qty,
                        "taxCode": tax_code,
                        "amt": gross_amount,
                        "discount": 0.0,
                    },
                }
            )
        )

    return lines


def get_totals(lines):
    """Receipt totals. Discounts are already inside the line amounts, so it stays zero."""
    net_amount = flt(sum(line.net_amount for line in lines), 2)
    tax_amount = flt(sum(line.tax_amount for line in lines), 2)

    return {
        "totalTaxExcl": net_amount,
        "totalTaxIncl": flt(net_amount + tax_amount, 2),
        "totalTax": tax_amount,
        "discount": 0.0,
    }


def get_vat_totals(lines):
    """Net and tax amounts per tax code."""
    vat_totals = {}

    for line in lines:
        row = vat_totals.setdefault(
            line.tax_code,
            {"vatRate": line.tax_code, "nettAmount": 0.0, "taxAmount": 0.0},
        )
        row["nettAmount"] = flt(row["nettAmount"] + line.net_amount, 2)
        row["taxAmount"] = flt(row["taxAmount"] + line.tax_amount, 2)

    return list(vat_totals.values())


def get_customer_name(doc):
    name = remove_special_characters(doc.customer_name or doc.customer)
    return name[:MAX_CUSTOMER_NAME_LENGTH].strip()


def get_payment(doc, total_tax_incl):
    """The single payment DIRM VFD accepts per receipt.

    Mixed tender cannot be expressed in this schema, so the largest one names
    the type and the amount is always the receipt total.
    """
    payment_rows = doc.get("payments") or []
    if not payment_rows:
        return {"pmtType": DEFAULT_PAYMENT_TYPE, "pmtAmount": total_tax_incl}

    tendered = max(payment_rows, key=lambda row: flt(row.base_amount))
    payment_type = get_payment_type(tendered.mode_of_payment)

    # TODO: follow-up about using 'INVOICE' as pmtType especially for credit invoices
    # since DIRM VFD currently does not support 'INVOICE' as pmtType
    return {
        "pmtType": DEFAULT_PAYMENT_TYPE if payment_type == "INVOICE" else payment_type,
        "pmtAmount": total_tax_incl,
    }


def get_payment_type(mode_of_payment):
    payment_type = frappe.get_cached_value(
        "Mode of Payment", mode_of_payment, "vfd_pmttype"
    )
    if not payment_type:
        frappe.throw(
            _("VFD PMTTYPE not setup in Mode of Payment {0}").format(mode_of_payment)
        )

    return payment_type


def refresh_session_tokens():
    """Scheduled: keep a live token for every company that uses DIRM VFD.

    Posting refreshes an expired token on its own, so a failure here only costs
    the head start.
    """
    rows = frappe.get_all(SETTINGS_DOCTYPE, fields=["name", "token", "token_expires"])

    for row in rows:
        if is_token_fresh(row.token, row.token_expires):
            continue

        try:
            frappe.get_doc(SETTINGS_DOCTYPE, row.name).get_session_token()
        except Exception:
            frappe.log_error(
                title=f"DIRM VFD Token Refresh Failed: {row.name}",
                message=frappe.get_traceback(),
            )


def is_token_fresh(token, token_expires):
    """True while the token has more than the renewal margin left."""
    if not token or not token_expires:
        return False

    renew_after = add_to_date(now_datetime(), minutes=TOKEN_RENEWAL_MARGIN_MINUTES)
    return get_datetime(token_expires) > renew_after


@frappe.whitelist()
def post_fiscal_receipt(
    doc: Document | None = None,
    method: str = "POST",
    payload: str | None = None,
    invoice_id: str | None = None,
    preview: bool = False,
):
    """Post a fiscal receipt to DIRM VFD.

    Parameters
    ----------
    doc : object
    Sales Invoice document. Required when invoice_id is not given.
    method : str
    Caller context. "on_submit" saves the invoice, anything else writes to the database.
    payload : str
    JSON payload coming from the preview dialog. Built here when not given.
    invoice_id : str
    Sales Invoice name, used when doc is not given.
    preview : bool
    Passed back to the caller so the frontend knows the payload came from a preview.

    Returns
    -------
    dict
    Response data, provider name, preview flag and whether TRA accepted the receipt.
    """
    if not doc and not invoice_id:
        frappe.throw(_("Sales Invoice is required!"))

    if not doc:
        doc = frappe.get_doc("Sales Invoice", invoice_id)

    validate_postable(doc)

    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE, doc.company)
    if not settings.is_token_valid:
        settings.get_session_token()

    if not payload:
        # Payloads from the preview dialog are already JSON strings.
        payload = json.dumps(get_payload(doc))

    response, headers, status_code = send_dirm_vfd_request(
        "post_receipt", settings, payload
    )
    receipt = response.get("data") or {}
    is_posted = cint(response.get("status")) == SUCCESS_STATUS

    posting = record_posting(doc, response, payload, headers, status_code)

    invoice_values = {
        "vfd_status": "Success" if is_posted else "Failed",
        "vfd_posting_info": posting.name,
    }
    if is_posted:
        invoice_values.update(
            {
                "vfd_rctnum": receipt.get("rctNum"),
                "vfd_rctvnum": receipt.get("traReceiptVerificationCode"),
                "vfd_verification_url": receipt.get("traReceiptVerificationUrl"),
                "vfd_date": posting.date,
                "vfd_time": posting.time,
            }
        )

    if method == "on_submit":
        doc.update(invoice_values)
        doc.save(ignore_permissions=True)
    else:
        frappe.db.set_value("Sales Invoice", doc.name, invoice_values)
        # The receipt is fiscalised at TRA and cannot be recalled, so the invoice
        # must keep it even if a later step of this request fails.
        frappe.db.commit()  # nosemgrep

    doc.add_comment(
        "Comment",
        _("DIRM VFD Receipt: {0}, Z Number: {1}, Status: {2}").format(
            receipt.get("rctNum"),
            receipt.get("zNum"),
            response.get("statusDesc") or response.get("status"),
        ),
    )

    return {
        "data": response,
        "vfd_provider": get_provider().name,
        "preview": preview,
        "success": is_posted,
    }


def validate_postable(doc):
    """Refuse invoices that must not reach TRA, or must not reach it twice."""
    if doc.vfd_status == "Success":
        frappe.throw(_("Sales Invoice {0} is already sent to TRA").format(doc.name))

    if doc.is_not_vfd_invoice or doc.is_return:
        frappe.throw(_("Sales Invoice {0} is not a VFD invoice").format(doc.name))


def record_posting(doc, response, payload, headers, status_code):
    """Keep the request and the DIRM VFD answer for audit."""
    receipt = response.get("data") or {}
    posted_on = (
        get_datetime(receipt.get("dateTime")) if receipt.get("dateTime") else None
    )

    # The bearer token must not be stored with the request it authorised.
    safe_headers = dict(headers or {})
    if "Authorization" in safe_headers:
        safe_headers["Authorization"] = "Bearer ***"

    posting = frappe.new_doc("VFD Provider Posting")
    posting.sales_invoice = doc.name
    posting.rctnum = receipt.get("rctNum")
    posting.date = posted_on.date() if posted_on else nowdate()
    posting.time = posted_on.time() if posted_on else nowtime()
    posting.req_headers = str(safe_headers)
    posting.req_data = payload
    posting.ackcode = response.get("status") or status_code
    posting.ackmsg = str(response)
    posting.save(ignore_permissions=True)

    return posting


def get_provider():
    """The VFD Provider record wired to these settings, whatever it is named."""
    name = frappe.db.get_value(
        "VFD Provider", {"vfd_provider_settings": SETTINGS_DOCTYPE}
    )
    if not name:
        frappe.throw(_("No VFD Provider uses {0}").format(SETTINGS_DOCTYPE))

    return frappe.get_cached_doc("VFD Provider", name)


def send_dirm_vfd_request(call_type, settings, payload=None):
    """POST to a DIRM VFD endpoint.

    Parameters
    ----------
    call_type : str
    Attribute key of the endpoint on the VFD Provider. e.g. "get_token".
    settings : object
    DIRM VFD Settings document of the company making the call.
    payload : str
    JSON payload to post.

    Returns
    -------
    tuple
    Parsed response body, the request headers and the HTTP status code.
    """
    provider = get_provider()
    url = f"{provider.base_url.strip()}{provider.get_endpoint(call_type).strip()}"

    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
    }
    if call_type != "get_token":
        headers["Authorization"] = f"Bearer {settings.get_password('token')}"

    data, status_code = request_with_retry(url, payload, headers)
    return data, headers, status_code


def request_with_retry(url, payload, headers):
    """POST to DIRM VFD, retrying transport failures only."""
    for attempt in range(REQUEST_ATTEMPTS):
        try:
            response = requests.request(
                method="POST",
                url=url,
                data=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        except Exception as error:
            if attempt == REQUEST_ATTEMPTS - 1:
                frappe.log_error(
                    title=str(error)[:140] or "DIRM VFD Request Failed",
                    message=frappe.get_traceback(),
                )
                raise

            sleep(3 * attempt + 1)
            continue

        if not response.ok:
            # The session payload holds the password, so it is left out of the log.
            frappe.log_error(
                title="DIRM VFD Request Error",
                message=f"{url} - Status Code: {response.status_code}\n{response.text}",
            )
            frappe.throw(_("DIRM VFD error: {0}").format(response.text))

        return json.loads(response.text), response.status_code
