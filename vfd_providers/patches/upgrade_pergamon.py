"""Register or upgrade Pergamon without silently switching existing live traffic."""
import frappe


def execute():
    if not frappe.db.exists("DocType", "Pergamon VFD Settings"):
        return
    name = frappe.db.get_value("VFD Provider", {"vfd_provider_settings": "Pergamon VFD Settings"})
    if not name:
        frappe.get_doc({"doctype": "VFD Provider", "vfd_provider": "Pergamon",
            "vfd_provider_settings": "Pergamon VFD Settings", "sandbox": 1}).insert(ignore_permissions=True)
        return
    provider = frappe.get_doc("VFD Provider", name)
    provider.set_endpoints()
    # Existing records require explicit production configuration. Never route them
    # automatically to the sandbox using existing credentials.
    if not provider.sandbox and not frappe.conf.get("pergamon_production_url"):
        for row in provider.attributes:
            if row.is_new():
                row.db_insert()
        return
    provider.save(ignore_permissions=True)
