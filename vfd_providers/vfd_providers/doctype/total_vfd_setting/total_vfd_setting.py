# Copyright (c) 2023, Aakvatech Limited and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document
from time import sleep
import frappe, json, requests
from frappe import _
from frappe.utils import nowdate, nowtime, format_datetime, flt


class TotalVFDSetting(Document):
    pass


def post_fiscal_receipt(doc, method="POST"):
    """Post fiscal receipt to Total VFD
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
    total_vfd_setting = frappe.get_doc("Total VFD Setting", doc.company)
    doc.vfd_date = doc.vfd_date or nowdate()
    doc.vfd_time = format_datetime(str(nowtime()), "HH:mm:ss")

    if total_vfd_setting.is_vat_grouped:
        vat_grouped = 1
    else:
        vat_grouped = 0
    items = []
    vat_group_totals = {}
    tax_map = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"}
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
                    "id": f"""Items in VAT Group {vat_group_entry["vat_group"]}""",
                    "name": f"""Items in VAT Group {vat_group_entry["vat_group"]}""",
                    "price": flt(vat_group_entry["total_price"], precision=2),
                    "qty": 1,
                    "vatGroup": vat_group_entry["vat_group"],
                    "discount": 0.0,
                }
            )

    vfd_cust_id_type = doc.vfd_cust_id_type[:1] or "6"
    payload = {
        "serial": total_vfd_setting.serial_id,
        "referenceNumber": doc.name,
        "customer": {
            "name": doc.customer_name,
            "idType": vfd_cust_id_type,
            "idValue": doc.vfd_cust_id if vfd_cust_id_type != "6" else "",
            "mobile": "",
        },
        "payments": [
            {
                "type": "invoice",
                "amount": doc.base_grand_total,
            }
        ],
        "items": items,
    }

    payload = json.dumps(payload)

    vfd_provider_posting_doc = frappe.new_doc("VFD Provider Posting")

    data = send_total_vfd_request(
        "sales",
        doc.company,
        payload,
        "POST",
        vfd_provider_posting_doc=vfd_provider_posting_doc,
    )

    vfd_provider_posting_doc.sales_invoice = doc.name
    vfd_provider_posting_doc.rctnum = doc.vfd_rctvnum
    vfd_provider_posting_doc.date = doc.vfd_date
    vfd_provider_posting_doc.time = doc.vfd_time
    vfd_provider_posting_doc.ackmsg = str(data)
    vfd_provider_posting_doc.save()

    if method == "on_submit":
        doc.vfd_status = "Success"
        doc.vfd_verification_url = data.get("verificationLink")
        doc.vfd_rctvnum = data.get("rctvnum")
        doc.vfd_date = data.get("localDate")
        doc.vfd_time = data.get("localTime")
    elif method == "POST":
        frappe.db.set_value(
            "Sales Invoice", doc.name, "vfd_rctvnum", data.get("rctvnum")
        )
        frappe.db.set_value("Sales Invoice", doc.name, "vfd_status", "Success")
        frappe.db.set_value(
            "Sales Invoice", doc.name, "vfd_date", data.get("localDate")
        )
        frappe.db.set_value(
            "Sales Invoice", doc.name, "vfd_time", data.get("localTime")
        )
        frappe.db.set_value(
            "Sales Invoice",
            doc.name,
            "vfd_verification_url",
            data.get("verificationLink"),
        )
        frappe.db.commit()
    return data


def send_total_vfd_request(
    call_type,
    company,
    payload=None,
    type="GET",
    total_vfd_setting=None,
    vfd_provider_posting_doc=None,
):
    """Send request to Total VFD API
    Parameters
    ----------
    call_type : str
    Type of call to make. e.g. "get_serial_info", "post_fiscal_receipt", "account_info", etc.
    company : str
    Company to get Total VFD settings from
    payload : dict
    Payload to send to Total VFD API
    type : str
    Type of request to make. e.g. "GET", "POST", "PUT", etc.
    total_vfd_setting : object
    Python object which is expected to be from Total VFD Setting doctype.
    vfd_provider_posting_doc : object
    Python object which is expected to be from VFD Provider Posting doctype.

    Returns
    -------
    data : dict
    Dictionary with response from Total VFD API
    """
    total_vfd = frappe.get_doc("VFD Provider", "TotalVFD")
    if not total_vfd:
        frappe.throw(_("Total VFD is not setup!"))
    if not total_vfd_setting:
        total_vfd_setting = frappe.get_cached_doc("Total VFD Setting", company)
    url = (
        total_vfd.base_url
        + frappe.get_list(
            "VFD Provider Attribute",
            filters={"parent": "TotalVFD", "key": call_type},
            fields=["value"],
            ignore_permissions=True,
        )[0].value
    )
    headers = {
        "Authorization": "Bearer " + total_vfd_setting.get_password("bearer_token"),
        "x-active-business": total_vfd_setting.get_password("x_active_business"),
        "Content-Type": "application/json",
    }

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
            if res.ok or res.status_code == 409:
                data = json.loads(res.text) if res.ok else json.loads(res.text)["data"]
                frappe.log_error(
                    title="Send Request OK",
                    message=f"Send Request: {url} - Status Code: {res.status_code}\n{res.text}",
                )
            else:
                data = []
                frappe.log_error(
                    title="Send Request Error",
                    message=f"Send Request: {url} - Status Code: {res.status_code}\n{res.text}\n{payload}",
                )
                frappe.throw(f"Error is {res.status_code}: {res.text}")

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
                vfd_provider_posting_doc.ackcode = data["status"] or 0
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
                    title=str(e)[:140] if e else "Send Total VFD Request Error",
                )
                frappe.throw(f"Connection failure is {res.text}")
                raise e
    return data
