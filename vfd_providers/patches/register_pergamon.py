"""Register Pergamon as a selectable VFD provider after models sync."""
import frappe


def execute():
    if not frappe.db.exists("DocType", "Pergamon VFD Settings"):
        return

    if not frappe.db.exists("VFD Provider", "Pergamon"):
        provider = frappe.get_doc({
            "doctype": "VFD Provider",
            "vfd_provider": "Pergamon",
            "vfd_provider_settings": "Pergamon VFD Settings",
            "vfd_provider_controller": "vfd_providers.vfd_providers.doctype.pergamon_vfd_settings.pergamon_vfd_settings",
            # Deliberately no embedded credentials or fixed server IP.
        })
        provider.insert(ignore_permissions=True)
