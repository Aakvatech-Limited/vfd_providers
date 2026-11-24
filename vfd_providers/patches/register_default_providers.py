"""Seed documented provider masters without configuring any company."""

import frappe

from vfd_providers.patches.register_pergamon import execute as register_pergamon

PROVIDERS = (
    ("TotalVFD", "Total VFD Setting", "total_vfd_setting",
     "https://api.totalvfd.co.tz", {"sales": "/sales"}),
    ("VFDPlus", "VFDPlus Settings", "vfdplus_settings",
     "https://app.vfdplus.co.tz", {
         "post_fiscal_receipt": "/vfd-thirdparty-api/post_fiscal_receipt",
         "receipt_info": "/vfd-thirdparty-api/receipt_info",
         "account_info": "/vfd-thirdparty-api/account_info",
         "serial_info": "/vfd-thirdparty-api/serial_info",
     }),
    ("SimplifyVFD", "Simplify VFD Settings", "simplify_vfd_settings",
     "https://simplify.co.tz/partner/v1", {
         "login": "/auth/user/login",
         "refresh": "/auth/user/token/refresh",
         "createIssuedInvoice": "/invoice/createIssuedInvoice",
     }),
)


def execute():
    for name, settings, module, base_url, endpoints in PROVIDERS:
        # Never replace an existing site's endpoint configuration.
        if frappe.db.exists("VFD Provider", {"vfd_provider": name}):
            continue
        frappe.get_doc({
            "doctype": "VFD Provider",
            "vfd_provider": name,
            "vfd_provider_settings": settings,
            "vfd_provider_controller": (
                f"vfd_providers.vfd_providers.doctype.{module}.{module}"
            ),
            "base_url": base_url,
            "attributes": [
                {"key": key, "value": value} for key, value in endpoints.items()
            ],
        }).insert(ignore_permissions=True)

    register_pergamon()
