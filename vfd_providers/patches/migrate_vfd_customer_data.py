import frappe


def execute():
    def field_exists(doctype, fieldname):
        return frappe.db.has_column(doctype, fieldname)

    def field_not_empty_filter(fieldname):
        return [fieldname, "not in", (None, "")]

    def process_batch(doctype, fields, conditions, limit_page_length):
        start = 0
        while True:
            records = frappe.get_all(
                doctype,
                fields=fields,
                filters=conditions,
                limit_start=start,
                limit_page_length=limit_page_length,
                order_by="creation desc",
            )
            if not records:
                break

            for record in records:
                frappe.db.set_value(
                    doctype,
                    record.name,
                    "vfd_cust_id_type",
                    record.vfd_custidtype,
                    update_modified=False,
                )
                frappe.db.set_value(
                    doctype,
                    record.name,
                    "vfd_cust_id",
                    record.vfd_custid,
                    update_modified=False,
                )
            frappe.db.commit()
            start += limit_page_length

    if field_exists("Customer", "vfd_cust_id_type") and field_exists(
        "Customer", "vfd_cust_id"
    ):
        conditions = [
            field_not_empty_filter("vfd_custidtype"),
            field_not_empty_filter("vfd_custid"),
        ]
        process_batch(
            "Customer",
            fields=[
                "name",
                "vfd_cust_id_type",
                "vfd_cust_id",
                "vfd_custidtype",
                "vfd_custid",
            ],
            conditions=conditions,
            limit_page_length=5000,
        )


def delete():

    def delete_custom_field(doctype, fieldname):
        custom_field_name = f"{doctype}-{fieldname}"
        if frappe.db.exists("Custom Field", custom_field_name):
            custom_field_doc = frappe.get_doc("Custom Field", custom_field_name)
            custom_field_doc.delete()
            frappe.db.commit()

    delete_custom_field("Customer", "vfd_custidtype")
    delete_custom_field("Customer", "vfd_custid")
