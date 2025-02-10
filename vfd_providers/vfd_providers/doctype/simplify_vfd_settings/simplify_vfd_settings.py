# Copyright (c) 2023, Aakvatech Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from time import sleep
import frappe, json, requests
from frappe import _
from frappe.utils import nowdate, nowtime, format_datetime, flt, now_datetime, add_to_date
import datetime


class SimplifyVFDSettings(Document):
    @frappe.whitelist()
    def get_bearer_token(self):
        """Get bearer token from Simplify VFD"""

        if not self.username or not self.password:
            frappe.throw(_("Username and Password are required!"))
        
        payload = {
            "username": self.username,
            "password": self.get_password(),
        }

        data = send_simplify_vfd_request("login", self.company, json.dumps(payload), "POST")
        token = data.get("token")
        refresh_token = data.get("refresh_token")
        token_expires = add_to_date(now_datetime(), minutes=25)

        self.db_set("bearer_token", token)
        self.db_set("refresh_token", refresh_token)
        self.db_set("token_expires", token_expires)
        frappe.db.commit()

        self.reload()
        return True
    
    def refresh_bearer_token(self):
        """Refresh bearer token from Simplify VFD"""

        if not self.refresh_token:
            frappe.throw(_("Refresh Token is not found, Please set username and password and generate the token!"))
        
        payload = {
            "refresh_token": self.get_passord("refresh_token"),
        }

        data = send_simplify_vfd_request(
            "refresh", self.company, json.dumps(payload), "POST"
        )
        token = data.get("token")
        refresh_token = data.get("refresh_token")
        token_expires = add_to_date(now_datetime(), minutes=20)
        self.db_set("bearer_token", token)
        self.db_set("refresh_token", refresh_token)
        self.db_set("token_expires", token_expires)

        frappe.db.commit()
        self.reload()

        return True

@frappe.whitelist()
def get_token():
    """Refresh bearer token from Simplify VFD"""

    setting_companies = frappe.get_all("Simplify VFD Settings", fields=["name"], pluck='name')

    for company in setting_companies:
        doc = frappe.get_cached_doc("Simplify VFD Settings", company)
        if doc.token_expires and doc.token_expires <= now_datetime():
            doc.refresh_bearer_token()
        

def post_fiscal_receipt(doc, method="POST"):
    """Post fiscal receipt to Simplify VFD
    Parameters
    ----------
    doc : object
    Python object which is expected to be from Sales Invoice doctype.
    method : str
    Method name which is calling this function. e.g. POST, validate, on_update, etc.

    Returns
    -------
    Nothing
    """
    simplify_vfd_settings = frappe.get_doc("Simplify VFD Settings", doc.company)
    doc.vfd_date = doc.vfd_date or nowdate()
    doc.vfd_time = format_datetime(str(nowtime()), "HH:mm:ss")

    if simplify_vfd_settings.is_vat_grouped:
        vat_grouped = 1
    else:
        vat_grouped = 0
    
    items = []
    vat_group_totals = {}
    tax_map = {
        "1": "STANDARD",
        "2": "SPECIAL_RATE",
        "3": "ZERO_RATED",
        "4": "SPECIAL_RELIEF",
        "5": "EXEMPTED",
    }
    for item in doc.items:
        vat_rate_id = frappe.get_cached_value(
            "Item Tax Template", item.item_tax_template, "vfd_taxcode"
        )[:1]
        vat_group = tax_map[vat_rate_id]
        if vat_group == "A":
            if item.base_net_amount == item.base_amount:
                # both amounts are same if the price is exclusive of VAT
                price = flt(item.base_net_amount * 1.18, precision=2)
            else:
                price = flt(item.base_amount, precision=2)
        else:
            price = flt(item.base_amount, precision=2)
        # Check if the VAT group already exists in the dictionary; if not, initialize it
        if vat_group not in vat_group_totals:
            vat_group_totals[vat_group] = 0

        # Add the calculated price to the respective VAT group's total
        vat_group_totals[vat_group] += flt(price, precision=2)
        items.append(
            {
                "id": item.item_code,
                "name": item.item_name,
                "price": price,
                "qty": item.qty,
                "vatGroup": vat_group,
                "discount": 0.0,
            }
        )
    # Convert the aggregated totals into a list of dictionaries
    vat_group_totals_list = [
        {"vat_group": vat_group, "total_price": total_price}
        for vat_group, total_price in vat_group_totals.items()
    ]

    if vat_grouped:
        # Re-create items list based on VAT group totals
        items = []
        for vat_group_entry in vat_group_totals_list:
            items.append(
                {
                    "description": f"""Items in VAT Group {vat_group_entry["vat_group"]}""",
                    "quantity": 1,
                    "unitAmount": flt(vat_group_entry["total_price"], precision=2),
                    "discountRate": 0.0,
                    "taxType": vat_group_entry["vat_group"],
                }
            )

    vfd_cust_id_type = doc.vfd_cust_id_type[:1] or "6"
    """VFD Customer ID Type Mapping
        1- TAX_IDENTIFICATION_NUMBER
        2- DRIVING_LICENCE
        3- VOTERS_NUMBER
        4- PASSPORT
        5- NATIONAL_IDENTIFICATION_AUTHORITY
        6- NO_IDENTIFICATION
    """
    vfd_cust_id_type_map = {
        "1": "TAX_IDENTIFICATION_NUMBER",
        "2": "DRIVING_LICENCE",
        "3": "VOTERS_NUMBER",
        "4": "PASSPORT",
        "5": "NATIONAL_IDENTIFICATION_AUTHORITY",
        "6": "NO_IDENTIFICATION",
    }
    payload = {
        "dateTime": doc.vfd_date,
        "customer": {
            "identificationType": vfd_cust_id_type_map[vfd_cust_id_type],
            "identificationNumber": doc.vfd_cust_id if vfd_cust_id_type != "6" else "",
            "vatRegistrationNumber": doc.vat_id or "",
            "name": doc.customer_name,
            "mobileNumber": "",
            "email": "",
        },
        "invoiceAmountType": "INCLUSIVE",
        "items": items,
        "payments": [
            {
                "type": "INVOICE",
                "amount": (
                    doc.base_total
                    if doc.base_grand_total < doc.base_total
                    else doc.base_grand_total
                ),
            }
        ],
        "partnerInvoiceId": doc.name,
    }

    payload = json.dumps(payload)

    vfd_provider_posting_doc = frappe.new_doc("VFD Provider Posting")

    data = send_simplify_vfd_request(
        "createIssuedInvoice",
        doc.company,
        payload,
        "POST",
        vfd_provider_posting_doc=vfd_provider_posting_doc,
    )

    dt_object = datetime.strptime(data.get("issuedAt"), "%Y-%m-%d %H:%M:%S")

    # Extract date and time
    date_part = dt_object.date()
    time_part = dt_object.time()

    vfd_provider_posting_doc.sales_invoice = doc.name
    vfd_provider_posting_doc.rctnum = doc.vfd_rctvnum
    vfd_provider_posting_doc.date = date_part
    vfd_provider_posting_doc.time = time_part
    vfd_provider_posting_doc.ackmsg = str(data)
    vfd_provider_posting_doc.save()

    if method == "on_submit":
        doc.vfd_status = "Success"
        doc.vfd_verification_url = data.get("verificationUrl")
        doc.vfd_rctvnum = data.get("verificationCode")
        doc.vfd_date = date_part
        doc.vfd_time = time_part
    elif method == "POST":
        frappe.db.set_value(
            "Sales Invoice", doc.name, "vfd_rctvnum", data.get("verificationCode")
        )
        frappe.db.set_value("Sales Invoice", doc.name, "vfd_status", "Success")

        frappe.db.set_value("Sales Invoice", doc.name, "vfd_date", date_part)
        frappe.db.set_value("Sales Invoice", doc.name, "vfd_time", time_part)
        frappe.db.set_value(
            "Sales Invoice",
            doc.name,
            "vfd_verification_url",
            data.get("verificationUrl"),
        )
        # Add invoiceId into the doc comments:
        doc.add_comment(
            "Comment",
            f"VFD Invoice ID: {data.get('invoiceId')}",
        )
        frappe.db.commit()
    return data


def send_simplify_vfd_request(
    call_type,
    company,
    payload=None,
    type="GET",
    simplify_vfd_settings=None,
    vfd_provider_posting_doc=None,
):
    """Send request to Simplify VFD API
    Parameters
    ----------
    call_type : str
    Type of call to make. e.g. "get_serial_info", "post_fiscal_receipt", "account_info", etc.
    company : str
    Company to get Simplify VFD settings from
    payload : dict
    Payload to send to Simplify VFD API
    type : str
    Type of request to make. e.g. "GET", "POST", "PUT", etc.
    simplify_vfd_settings : object
    Python object which is expected to be from Simplify VFD Settings doctype.
    vfd_provider_posting_doc : object
    Python object which is expected to be from VFD Provider Posting doctype.

    Returns
    -------
    data : dict
    Dictionary with response from Simplify VFD API
    """
    simplify_vfd = frappe.get_cached_doc("VFD Provider", "SimplifyVFD")

    if not simplify_vfd_settings:
        simplify_vfd_settings = frappe.get_cached_doc(simplify_vfd.vfd_provider_settings, company)
    
    simplify_vfd_endpoint = [row for row in simplify_vfd.attributes if row.key == call_type][0].value

    url = f"{simplify_vfd.base_url.strip()}{simplify_vfd_endpoint.strip()}"

    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
    }
    if call_type not in ['login', 'refresh']:
        headers["Authorization"] = f"Bearer {simplify_vfd_settings.get_password('bearer_token')}"

    data = None
    for i in range(3):
        try:
            res = requests.request(
                method=type,
                url=url,
                data=payload if payload else None,
                headers=headers,
                timeout=500,
            )
            if res.ok:
                data = json.loads(res.text)
            else:
                data = []
                frappe.log_error(
                    title="Send Request Error",
                    message=f"Send Request: {url} - Status Code: {res.status_code}\n{res.text}\n{payload}",
                )
                frappe.throw(f"Error is {res.text}")
            
            if vfd_provider_posting_doc:
                vfd_provider_posting_doc.req_headers = (
                    json.dumps(headers, ensure_ascii=False)
                    .replace("\\'", "'")
                    .replace('\\"', '"')
                )
                vfd_provider_posting_doc.req_data = (
                    json.dumps(payload, ensure_ascii=False)
                    .replace("\\'", "'")
                    .replace('\\"', '"')
                )
                vfd_provider_posting_doc.ackcode = data["status"]
                vfd_provider_posting_doc.ackmsg = (
                    str(data).replace("\\'", "'").replace('\\"', '"')
                )

            break
        except Exception as e:
            sleep(3 * i + 1)
            if i != 2:
                continue
            else:
                frappe.log_error(
                    message=frappe.get_traceback(),
                    title=str(e)[:140] if e else "Send Simplify VFD Request Error",
                )
                raise e
    return data
