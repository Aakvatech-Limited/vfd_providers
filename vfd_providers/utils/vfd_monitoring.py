# -*- coding: utf-8 -*-
# Copyright (c) 2024, Aakvatech Limited and contributors
# For license information, please see license.txt

"""
VFD Invoice Monitoring System
Monitors VFD invoice posting status and sends alerts for pending invoices
"""

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.utils import add_days, getdate, formatdate, date_diff


# Constants
PENDING_STATUSES = ["Pending", "Failed", "Not Sent"]
ALERT_ROLES = ["System Manager", "Accounts Manager"]
DEFAULT_DAYS_THRESHOLD = 2


def get_pending_vfd_invoices(days_threshold=DEFAULT_DAYS_THRESHOLD):
    """
    Get all Sales Invoices with VFD status 'Pending', 'Failed', or 'Not Sent'
    that are older than the specified days threshold

    Args:
        days_threshold (int): Number of days to consider an invoice as stuck

    Returns:
        list: List of pending invoices with essential fields only
    """
    threshold_date = add_days(getdate(), -days_threshold)

    # Use Frappe Query Builder - fetch only essential fields
    SalesInvoice = frappe.qb.DocType("Sales Invoice")

    query = (
        frappe.qb.from_(SalesInvoice)
        .select(
            SalesInvoice.name,
            SalesInvoice.customer,
            SalesInvoice.company,
            SalesInvoice.posting_date,
            SalesInvoice.vfd_status
        )
        .where(SalesInvoice.docstatus == 1)
        .where(SalesInvoice.is_not_vfd_invoice == 0)
        .where(SalesInvoice.is_return == 0)
        .where(SalesInvoice.vfd_status.isin(PENDING_STATUSES))
        .where(SalesInvoice.posting_date <= threshold_date)
        .orderby(SalesInvoice.company)
        .orderby(SalesInvoice.posting_date)
    )

    invoices = query.run(as_dict=True)

    # Calculate days_pending in Python for better compatibility
    current_date = getdate()
    for invoice in invoices:
        if invoice.get("posting_date"):
            invoice["days_pending"] = date_diff(current_date, invoice.get("posting_date"))

    return invoices


def send_vfd_pending_alert(pending_invoices, days_threshold=DEFAULT_DAYS_THRESHOLD):
    """
    Send email alerts for pending VFD invoices

    Args:
        pending_invoices (list): List of pending invoices
        days_threshold (int): Number of days threshold used
    """
    if not pending_invoices:
        frappe.log_error("No pending VFD invoices found", "VFD Monitoring")
        return

    # Get recipients - System Managers and Accounts Managers
    recipients = get_alert_recipients()

    if not recipients:
        frappe.log_error("No recipients found for VFD alerts", "VFD Monitoring")
        return

    # Prepare email content
    subject = _("VFD Invoice Posting Alert - {0} Invoices Pending for {1}+ Days").format(
        len(pending_invoices), days_threshold
    )
    message = prepare_email_message(pending_invoices, days_threshold)
    # frappe.throw(str(message))
    # Send email
    frappe.sendmail(
        recipients=recipients,
        subject=subject,
        message=message,
        delayed=False,
        reference_doctype="Sales Invoice",
        reference_name=None,
    )

    # Log success
    frappe.log_error(
        f"VFD Alert sent to {len(recipients)} recipients for {len(pending_invoices)} invoices",
        "VFD Monitoring Success"
    )


def get_alert_recipients():
    """
    Get list of users who should receive VFD alerts

    Returns:
        list: List of email addresses
    """
    # Use Frappe Query Builder
    User = frappe.qb.DocType("User")
    HasRole = frappe.qb.DocType("Has Role")

    query = (
        frappe.qb.from_(User)
        .inner_join(HasRole)
        .on(HasRole.parent == User.name)
        .select(User.email)
        .distinct()
        .where(HasRole.role.isin(ALERT_ROLES))
        .where(User.enabled == 1)
        .where(User.email.isnotnull())
        .where(User.email != "")
    )

    recipients = query.run(as_dict=False)
    return [r[0] for r in recipients if r[0]]


def prepare_email_message(pending_invoices, days_threshold):
    """
    Prepare simple email message with pending invoice details

    Args:
        pending_invoices (list): List of pending invoices
        days_threshold (int): Number of days threshold

    Returns:
        str: Simple HTML formatted email message
    """
    # Group invoices by company for better organization
    companies = {}
    for invoice in pending_invoices:
        company = invoice.get("company")
        if company not in companies:
            companies[company] = []
        companies[company].append(invoice)

    # Build email content
    message = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color: #d9534f;">⚠️ VFD Invoice Posting Alert</h2>
        <p>The following <strong>{len(pending_invoices)} invoices</strong> have been in <strong>Pending/Failed/Not Sent</strong> status for more than <strong>{days_threshold} days</strong>:</p>
    """

    # Add invoices grouped by company
    for company, invoices in companies.items():
        message += f"""
        <div style="margin-top: 20px; border-left: 3px solid #d9534f; padding-left: 15px;">
            <h3 style="color: #333; margin-bottom: 10px;">Company: {company}</h3>
            <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
                <thead>
                    <tr style="background-color: #f5f5f5;">
                        <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Invoice</th>
                        <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Customer</th>
                        <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Posting Date</th>
                        <th style="border: 1px solid #ddd; padding: 8px; text-align: center;">Days Pending</th>
                        <th style="border: 1px solid #ddd; padding: 8px; text-align: center;">VFD Status</th>
                    </tr>
                </thead>
                <tbody>
        """

        for invoice in invoices:
            invoice_link = frappe.utils.get_url_to_form("Sales Invoice", invoice.get("name"))
            message += f"""
                    <tr>
                        <td style="border: 1px solid #ddd; padding: 8px;">
                            <a href="{invoice_link}" target="_blank">{invoice.get('name')}</a>
                        </td>
                        <td style="border: 1px solid #ddd; padding: 8px;">{invoice.get('customer')}</td>
                        <td style="border: 1px solid #ddd; padding: 8px;">{formatdate(invoice.get('posting_date'))}</td>
                        <td style="border: 1px solid #ddd; padding: 8px; text-align: center;">{invoice.get('days_pending')} days</td>
                        <td style="border: 1px solid #ddd; padding: 8px; text-align: center;">{invoice.get('vfd_status')}</td>
                    </tr>
            """

        message += """
                </tbody>
            </table>
        </div>
        """

    # Add footer
    message += """
        <div style="margin-top: 30px; padding: 15px; background-color: #d9edf7; border-left: 4px solid #31708f;">
            <p style="margin: 0;"><strong>Action Required:</strong> Please review and retry posting these invoices to VFD.</p>
        </div>
    </div>
    """

    return message


def check_and_alert_pending_vfd_invoices(days_threshold=DEFAULT_DAYS_THRESHOLD):
    """
    Main function to check for pending VFD invoices and send alerts
    This function is called by the scheduled task

    Args:
        days_threshold (int): Number of days to consider an invoice as stuck
    """
    try:
        frappe.log_error("Starting VFD monitoring check", "VFD Monitoring")

        # Get pending invoices
        pending_invoices = get_pending_vfd_invoices(days_threshold)

        if not pending_invoices:
            frappe.log_error("No pending VFD invoices found", "VFD Monitoring")
            return

        # Send alert
        send_vfd_pending_alert(pending_invoices, days_threshold)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "VFD Monitoring Error")
        raise

