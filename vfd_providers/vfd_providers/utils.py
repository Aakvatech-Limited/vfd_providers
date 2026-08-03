import frappe
from frappe.utils import flt

def get_vat_amount(item, vat_group, precision=0):
    """
    Calculates the VAT-inclusive line item total for TRA VFD payload.
    Uses base_net_amount (in TZS) to account for all discounts (line & header).
    """
    # Net taxable amount in base currency (TZS) after all discounts
    net_total_tzs = item.get("base_net_amount") if item.get("base_net_amount") is not None else item.base_amount

    # Standard VAT Rate (18% - VAT Group 'A' or '1')
    if str(vat_group) in ["A", "1"]:
        vat_inclusive_amount = net_total_tzs * 1.18
    else:
        vat_inclusive_amount = net_total_tzs

    # Format precision if requested
    if precision > 0:
        return flt(vat_inclusive_amount, precision)
    return vat_inclusive_amount

