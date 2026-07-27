import frappe
from frappe.utils import flt

def get_vat_amount(item, vat_group, precision=0):
    vat_amount = 0

    # Net amount after item discounts and distributed header discounts
    net_total = item.base_net_amount if hasattr(item, "base_net_amount") and item.base_net_amount is not None else (item.net_amount if hasattr(item, "net_amount") else item.base_amount)

    if str(vat_group) in ["A", "1"]:
        if (
            (net_total + item.get("distributed_discount_amount", 0)) == item.base_amount
        ):
            # Amount is exclusive of VAT: apply 1.18 on final net_total after discounts
            amount = net_total * 1.18
            if precision > 0:
                vat_amount = flt(amount, precision)
            else:
                vat_amount = amount
        else:
            amount = net_total * 1.18
            if precision > 0:
                vat_amount = flt(amount, precision=2)
            else:
                vat_amount = amount
    else:
        if precision > 0:
            vat_amount = flt(net_total, precision=2)
        else:
            vat_amount = net_total

    return vat_amount

