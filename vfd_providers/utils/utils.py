import frappe
from frappe import _
from frappe.model.document import Document

from vfd_providers.vfd_providers.doctype.dirm_vfd_settings.dirm_vfd_settings import (
    get_payload as get_dirm_vfd_payload,
    post_fiscal_receipt as dirm_vfd_post_fiscal_receipt,
)
from vfd_providers.vfd_providers.doctype.simplify_vfd_settings.simplify_vfd_settings import (
    get_payload as get_simplify_payload,
    post_fiscal_receipt as simplify_vfd_post_fiscal_receipt,
)
from vfd_providers.vfd_providers.doctype.total_vfd_setting.total_vfd_setting import (
    get_payload as get_total_vfd_payload,
    post_fiscal_receipt as total_vfd_post_fiscal_receipt,
)
from vfd_providers.vfd_providers.doctype.vfdplus_settings.vfdplus_settings import (
    get_payload as get_vfdplus_payload,
    post_fiscal_receipt as vfdplus_post_fiscal_receipt,
)

# Payload builder and posting function of each provider, keyed by settings
# doctype. A VFD Provider record can be renamed, its settings doctype cannot.
VFD_PROVIDER_HANDLERS = {
    "VFDPlus Settings": (get_vfdplus_payload, vfdplus_post_fiscal_receipt),
    "Total VFD Setting": (get_total_vfd_payload, total_vfd_post_fiscal_receipt),
    "Simplify VFD Settings": (get_simplify_payload, simplify_vfd_post_fiscal_receipt),
    "DIRM VFD Settings": (get_dirm_vfd_payload, dirm_vfd_post_fiscal_receipt),
}


@frappe.whitelist()
def generate_tra_vfd(
    docname: str,
    sinv_doc: Document | None = None,
    method: str = "POST",
    caller: str = "Frontend",
):
    if not sinv_doc:
        sinv_doc = frappe.get_doc("Sales Invoice", docname)

    if (
        sinv_doc.is_not_vfd_invoice
        or sinv_doc.vfd_status == "Success"
        or sinv_doc.is_return == 1
    ):
        return

    vfd_provider = get_company_vfd_provider(sinv_doc.company)
    if not vfd_provider:
        return

    vfd_provider_settings = vfd_provider.vfd_provider_settings
    handlers = VFD_PROVIDER_HANDLERS.get(vfd_provider_settings)
    if not handlers:
        frappe.throw(_("VFD Provider not supported"))

    get_payload, post_fiscal_receipt = handlers
    settings_info = get_settings_info(sinv_doc, vfd_provider_settings)

    if settings_info.get("enable_vfd_preview") == 1 and caller == "Frontend":
        return {
            "data": get_payload(sinv_doc),
            "vfd_provider": vfd_provider.name,
            "post_method": f"{post_fiscal_receipt.__module__}.{post_fiscal_receipt.__name__}",
            "preview": True,
        }

    return post_fiscal_receipt(doc=sinv_doc, method=method)


def get_company_vfd_provider(company):
    """VFD Provider set for the company, or None when VFD is not set up for it."""
    comp_vfd_provider = frappe.get_cached_doc("Company VFD Provider", company)
    if not comp_vfd_provider:
        return None

    vfd_provider = frappe.get_cached_doc("VFD Provider", comp_vfd_provider.vfd_provider)
    if not vfd_provider or not vfd_provider.vfd_provider_settings:
        return None

    return vfd_provider


def get_settings_info(sinv_doc, vfd_provider_settings):
    """Provider settings of the invoice company, refusing invoices before the start date."""
    settings_info = frappe.get_cached_value(
        vfd_provider_settings,
        sinv_doc.company,
        ["enable_vfd_preview", "vfd_start_date"],
        as_dict=True,
    )

    if not settings_info:
        frappe.throw(
            _("Please create <b>{0}</b> for company <b>{1}</b>").format(
                vfd_provider_settings, sinv_doc.company
            )
        )

    if not settings_info.get("vfd_start_date"):
        frappe.throw(_(f"Please set VFD Start Date in <b>{vfd_provider_settings}</b>"))

    if frappe.utils.getdate(sinv_doc.posting_date) < settings_info.get(
        "vfd_start_date"
    ):
        frappe.throw(
            _(
                f"VFD cannot be generated for Invoice before <b>{settings_info.get('vfd_start_date')}</b> \
                as per the settings in <b>{vfd_provider_settings}</b>"
            )
        )

    return settings_info


def autogenerate_vfd(doc, method):
    if doc.is_not_vfd_invoice or doc.vfd_status == "Success" or doc.is_return == 1:
        return

    if doc.is_auto_generate_vfd and doc.docstatus == 1:
        generate_tra_vfd(
            docname=doc.name, sinv_doc=doc, method=method, caller="Scheduler"
        )


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

        vfd_provider = frappe.get_cached_doc(
            "VFD Provider", comp_vfd_provider.vfd_provider
        )

        vfd_provider_settings = vfd_provider.vfd_provider_settings
        if not vfd_provider_settings:
            continue

        handlers = VFD_PROVIDER_HANDLERS.get(vfd_provider_settings)
        if not handlers:
            continue

        vfd_start_date = frappe.get_cached_value(
            vfd_provider_settings, company, "vfd_start_date"
        )

        if not vfd_start_date:
            continue

        invoices = frappe.db.get_all(
            "Sales Invoice",
            filters={
                "docstatus": 1,
                "company": company,
                "is_not_vfd_invoice": 0,
                "is_return": 0,
                # Not Sent covers invoices submitted without auto generation.
                "vfd_status": ["!=", "Success"],
                "posting_date": [">=", vfd_start_date],
            },
        )

        for invoice in invoices:
            post_invoice(invoice.name, handlers[1])

    frappe.local.flags.vfd_posting = False


def post_invoice(invoice_name, post_fiscal_receipt):
    """Post one invoice. A rejected invoice must not stop the rest of the run."""
    try:
        doc = frappe.get_doc("Sales Invoice", invoice_name)
        post_fiscal_receipt(doc=doc, method="POST")
    except Exception:
        frappe.db.rollback()
        frappe.log_error(
            title=f"VFD Posting Failed: {invoice_name}",
            message=frappe.get_traceback(),
        )


def clean_and_update_tax_id_info(doc, method):
    cleaned_tax_id = "".join(char for char in (doc.tax_id or "") if char.isdigit())
    doc.tax_id = cleaned_tax_id
    if doc.tax_id:
        doc.vfd_cust_id_type = "1- TIN"
        doc.vfd_cust_id = doc.tax_id
    else:
        doc.vfd_cust_id_type = "6- Other"
        doc.vfd_cust_id = "999999999"
