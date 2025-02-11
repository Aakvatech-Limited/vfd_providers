import click
import frappe
from frappe import _
from vfd_providers.vfd_providers.doctype.vfdplus_settings.vfdplus_settings import post_fiscal_receipt as vfdplus_post_fiscal_receipt
from vfd_providers.vfd_providers.doctype.total_vfd_setting.total_vfd_setting import post_fiscal_receipt as total_vfd_post_fiscal_receipt
from vfd_providers.vfd_providers.doctype.simplify_vfd_settings.simplify_vfd_settings import post_fiscal_receipt as simplify_vfd_post_fiscal_receipt


@frappe.whitelist()
def generate_tra_vfd(docname, sinv_doc=None, method="POST"):
    if not sinv_doc:
        sinv_doc = frappe.get_doc("Sales Invoice", docname)
    
    if sinv_doc.is_not_vfd_invoice or sinv_doc.vfd_status in ["Sent", "Success"]:
        return
    
    comp_vfd_provider = frappe.get_cached_doc("Company VFD Provider", sinv_doc.company)
    if not comp_vfd_provider:
        return
    
    vfd_provider = frappe.get_cached_doc("VFD Provider", comp_vfd_provider.vfd_provider)
    if not vfd_provider:
        return
    vfd_provider_settings = vfd_provider.vfd_provider_settings

    if not vfd_provider_settings:
        return
    
    if vfd_provider.name == "VFDPlus":
        vfdplus_post_fiscal_receipt(sinv_doc, method)
    
    elif vfd_provider.name == "TotalVFD":
        total_vfd_post_fiscal_receipt(sinv_doc, method)
    
    elif vfd_provider.name == "SimplifyVFD":
        simplify_vfd_post_fiscal_receipt(sinv_doc, method)
    else:
        frappe.throw(_("VFD Provider not supported"))


def autogenerate_vfd(doc, method):
    if doc.is_not_vfd_invoice or doc.vfd_status in ["Sent", "Success"]:
        return
    
    if doc.is_auto_generate_vfd and doc.docstatus == 1:
        generate_tra_vfd(docname=doc.name, sinv_doc=doc, method=method)


def posting_all_vfd_invoices():
    if frappe.local.flags.vfd_posting:
        frappe.log_error(_("VFD Posting Flag found", "VFD Posting Flag found"))
        return
    
    frappe.local.flags.vfd_posting = True

    companies = frappe.get_all("Company", pluck="name")
    for company in companies:
        comp_vfd_provider = None
        if frappe.db.exists("Company VFD Provider", company):
            comp_vfd_provider = frappe.get_cached_doc("Company VFD Provider", company)
        else:
            continue

        vfd_provider = frappe.get_cached_doc("VFD Provider", comp_vfd_provider.vfd_provider)

        vfd_provider_settings = vfd_provider.vfd_provider_settings
        if not vfd_provider_settings:
            continue

        invoices = frappe.db.get_all(
            "Sales Invoice",
            filters={
                "docstatus": 1,
                "company": company,
                "is_not_vfd_invoice": 0,
                "vfd_status": ["not in", ["Sent", "Success"]],
            }
        )

        for invoice in invoices:
            doc = frappe.get_doc("Sales Invoice", invoice.name)

            if vfd_provider.name == "VFDPlus":
                vfdplus_post_fiscal_receipt(doc, "POST")
            
            elif vfd_provider.name == "TotalVFD":
                total_vfd_post_fiscal_receipt(doc, "POST")
            
            elif vfd_provider.name == "SimplifyVFD":
                simplify_vfd_post_fiscal_receipt(doc, "POST")

            else:
                continue
    
    frappe.local.flags.vfd_posting = False


def clean_and_update_tax_id_info(doc, method):
    cleaned_tax_id = "".join(char for char in (doc.tax_id or "") if char.isdigit())
    doc.tax_id = cleaned_tax_id
    if doc.tax_id:
        doc.vfd_cust_id_type = "1- TIN"
        doc.vfd_cust_id = doc.tax_id
    else:
        doc.vfd_cust_id_type = "6- Other"
        doc.vfd_cust_id = "999999999"
