frappe.ui.form.on("Sales Invoice", {
  refresh: function (frm) {},
  generate_vfd: (frm) => {
    if (!frm.doc.vfd_cust_id) {
      frappe.msgprint({
        title: __("Confirmation Required"),
        message: __("Are you sure you want to send VFD without TIN"),
        primary_action: {
          label: "Proceed",
          action(values) {
            _generate_vfd(frm);
            cur_dialog.cancel();
          },
        },
      });
    } else if (frm.doc.vfd_cust_id && frm.doc.vfd_cust_id != frm.doc.tax_id) {
      frappe.msgprint({
        title: __("Confirmation Required"),
        message: __("TIN an VFD Customer ID mismatch"),
        primary_action: {
          label: "Proceed",
          action(values) {
            _generate_vfd(frm);
            cur_dialog.cancel();
          },
        },
      });
    } else {
      _generate_vfd(frm);
    }
  },
});

function _generate_vfd(frm) {
  frappe.call({
    method: "vfd_providers.utils.utils.generate_tra_vfd",
    args: {
      docname: frm.doc.name,
    },
    freeze: true,
    freeze_message: __("Preparing VFD preview..."),
    callback: (r) => {
      if (!r.message) {
        frappe.msgprint(__("No payload returned from server"));
        return;
      }

      let payload = r.message.payload
      let vfd_provider = r.message.vfd_provider
      show_vfd_preview_dialog(frm, payload, vfd_provider);
    },
    error: () => {
      frappe.dom.unfreeze();
      frappe.msgprint(__("VFD Preview failed"));
    },
  });
}

function show_vfd_preview_dialog(frm, payload, vfd_provider) {
  const formatNumber = (val) =>
    new Intl.NumberFormat("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(flt(val));

  // Compute totals & taxes (assume STANDARD = 18% VAT, others = 0 for preview purposes)
  let totalIncl = 0;
  let taxAmount = 0;

  (payload.items || []).forEach((item) => {
    const lineTotal = (item.unitAmount || 0) * (item.quantity || 0);
    totalIncl += lineTotal;
    if (item.taxType === "STANDARD") {
      taxAmount += lineTotal * 0.18; // assumption based on VAT standard rate
    }
  });

  // If payments total is present and differs slightly, trust payments amount
  if (payload.payments && payload.payments.length) {
    const pTotal = flt(payload.payments.reduce((a, p) => a + (p.amount || 0), 0));
    if (pTotal) totalIncl = pTotal; // override
  }

  let totalExcl = totalIncl - taxAmount;

  // Guard against negative/NaN
  if (totalExcl < 0 || isNaN(totalExcl)) {
    totalExcl = 0;
  }

  if (isNaN(taxAmount)) {
    taxAmount = 0;
  }

  const company_name = (frm.doc.company || "").toUpperCase();
  let receipt_date = ''
  if (payload.dateTime && !["None", "null", "Invalid date", "undefined"].includes(String(payload.dateTime))) {
    const dt = frappe.datetime.str_to_obj(payload.dateTime);
    receipt_date = frappe.datetime.str_to_user(frappe.datetime.obj_to_str(dt, "YYYY-MM-DD"));
  } else {
    receipt_date = frappe.datetime.nowdate();
  }

  const receiptHTML = `
  <div class="vfd-preview-root">
    <style>
      .vfd-preview-root {font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, BlinkMacSystemFont, 'Roboto', 'Helvetica Neue', Arial, sans-serif; max-width:640px; margin:0 auto; font-size:12.5px; color:#222; line-height:1.35;}
      .vfd-center { text-align:center; }
      .vfd-muted { color:#555; }
      .vfd-heading { font-weight:600; letter-spacing:.5px; font-size:12px; text-transform:uppercase; margin:24px 0 6px; }
      .vfd-title { font-size:17px; font-weight:600; margin:0 0 2px; }
      .vfd-subgrid { display:flex; flex-wrap:wrap; gap:16px; margin:4px 0 4px; }
      .vfd-box { flex:1 1 240px; }
      .vfd-row { display:flex; align-items:flex-start; margin:2px 0; }
      .vfd-label { font-weight:500; width:110px; flex:0 0 110px; }
      .vfd-value { flex:1 1 auto; }
      .vfd-topline { border-top:1px solid #e4e6e9; margin:16px 0 0; }
      .vfd-hr { height:1px; background:#e4e6e9; border:0; margin:12px 0 16px; }
      table.vfd-table { width:100%; border-collapse:separate; border-spacing:0; font-size:12px; }
      table.vfd-table thead th { background:#f8f9fa; font-weight:600; padding:6px 8px; border:1px solid #e1e4e8; font-size:11px; text-transform:uppercase; letter-spacing:.5px; }
      table.vfd-table tbody td { padding:6px 8px; border:1px solid #eef0f2; vertical-align:top; }
      table.vfd-table tbody tr:nth-child(even) td { background:#fbfcfd; }
      .vfd-totals { margin-top:14px; display:flex; justify-content:flex-end; }
      .vfd-totals-inner { width:300px; }
      .vfd-totals-row { display:flex; justify-content:space-between; padding:5px 0; }
      .vfd-totals-row.border { border-top:1px solid #d9dde2; }
      .vfd-totals-row.emph { font-size:13px; font-weight:600; border-top:1px solid #d9dde2; border-bottom:1px solid #d9dde2; margin-top:4px; }
      .vfd-footer { margin-top:20px; font-size:11px; text-align:center; color:blue; }
      .vfd-receipt-banner { font-weight:600; font-size:12px; letter-spacing:1px; margin:0; }
      .vfd-header { margin-bottom:8px; }
    </style>
    <div class="vfd-center" style="margin-bottom:4px;">
      <div class="vfd-title">${frappe.utils.escape_html(company_name)}</div>
      <div class="vfd-muted" style="font-size:11.5px;">TIN: ${frappe.utils.escape_html(frm.doc.tax_id || '-')}&nbsp;&nbsp;|&nbsp;&nbsp;RECEIPT DATE: ${frappe.utils.escape_html(receipt_date)}</div>
    </div>
    <hr class="vfd-hr" />
    <div class="vfd-subgrid">
      <div class="vfd-box" style="padding-right:20px; font-size:11px;">
        <div class="vfd-row"><span class="vfd-label">Customer Name:</span><span class="vfd-value">${frappe.utils.escape_html(payload.customer?.name || '')}</span></div>
        <div class="vfd-row"><span class="vfd-label">Customer ID Type:</span><span class="vfd-value">${frappe.utils.escape_html(payload.customer?.identificationType || '')}</span></div>
        <div class="vfd-row"><span class="vfd-label">Customer ID:</span><span class="vfd-value">${frappe.utils.escape_html(payload.customer?.identificationNumber || 'n/a')}</span></div>
        <div class="vfd-row"><span class="vfd-label">VAT Reg No:</span><span class="vfd-value">${frappe.utils.escape_html(payload.customer?.vatRegistrationNumber || '')}</span></div>
      </div>
      <div class="vfd-box" style="padding-left:40px; border-left:2px solid #e4e6e9; font-size:11px;">
        <div class="vfd-row"><span class="vfd-label">Tax Type:</span><span class="vfd-value">${frappe.utils.escape_html(payload.invoiceAmountType || '')}</span></div>
        <div class="vfd-row"><span class="vfd-label">Invoice ID:</span><span class="vfd-value">${frappe.utils.escape_html(payload.partnerInvoiceId || frm.doc.name)}</span></div>
      </div>
    </div>
    <div class="vfd-heading" style="margin-top:18px; text-align:center;">Purchased Items</div>
    <table class="vfd-table">
      <thead>
        <tr>
          <th style="text-align:left;">Description</th>
          <th style="text-align:center; width:60px;">Qty</th>
          <th style="text-align:right; width:110px;">Unit Amount</th>
          <th style="text-align:right; width:120px;">Total Amount</th>
        </tr>
      </thead>
      <tbody>
        ${(payload.items || [])
          .map((it) => {
            const lineTotal = (it.unitAmount || 0) * (it.quantity || 0);
            return `<tr>
              <td>${frappe.utils.escape_html(it.description || '')}</td>
              <td style="text-align:center;">${formatNumber(it.quantity || 0)}</td>
              <td style="text-align:right;">${formatNumber(it.unitAmount || 0)}</td>
              <td style="text-align:right;">${formatNumber(lineTotal)}</td>
            </tr>`;
          })
          .join('')}
      </tbody>
    </table>
    <div class="vfd-totals">
      <div class="vfd-totals-inner">
        <div class="vfd-totals-row border" style="padding-top:8px;">
          <span>Total Excl of Tax:</span><span>${formatNumber(totalExcl)}</span>
        </div>
        <div class="vfd-totals-row">
          <span>Tax (18%):</span><span>${formatNumber(taxAmount)}</span>
        </div>
        <div class="vfd-totals-row emph">
          <span>Total Incl of Tax:</span><span>${formatNumber(totalIncl)}</span>
        </div>
      </div>
    </div>
    <div class="vfd-footer">Please verify the above details before sending to TRA.</div>
  </div>`;
  
  let method = ''
  if (vfd_provider === "VFDPlus") {
    method = "vfd_providers.vfd_providers.doctype.vfdplus_settings.vfdplus_settings.post_fiscal_receipt"
  } else if (vfd_provider === "TotalVFD") {
    method = "vfd_providers.vfd_providers.doctype.total_vfd_settings.total_vfd_settings.post_fiscal_receipt"
  } else if (vfd_provider === "SimplifyVFD") {
    method = "vfd_providers.vfd_providers.doctype.simplify_vfd_settings.simplify_vfd_settings.post_fiscal_receipt"
  }

  let d = new frappe.ui.Dialog({
    title: __("VFD Receipt Preview"),
    fields: [
      {
        fieldtype: "HTML",
        fieldname: "preview_html",
        options: receiptHTML,
      },
    ],
    primary_action_label: __("Send To TRA"),
    primary_action() {
      // Submit to TRA
      frappe
        .call({
          method: method,
          args: {
            method: "POST",
            payload: payload,
            invoice_id: frm.doc.name
          },
          freeze: true,
          freeze_message: __("Sending to TRA..."),
        })
        .then((res) => {
            d.hide();
            frm.reload_doc();
            if (res.message && res.message.success) {
              frappe.show_alert({
                message: __("VFD successfully sent to TRA"),
                indicator: "green",
              });
            } else {
              frappe.show_alert({
                message: __("VFD sending completed with errors"),
                indicator: "orange",
              });
            }
        })
        .fail((e) => {
          frappe.msgprint({
            title: __("Error"),
            message: __("Failed to send VFD to TRA"),
            indicator: "red",
          });
        });
    },
    secondary_action_label: __("Close"),
    secondary_action() {
      d.hide();
    },
  });

  d.$wrapper.find(".modal-content").css("width", "650px");

  d.show();
}


    // <div class="vfd-center vfd-header">
    //   <p class="vfd-receipt-banner">*** START OF LEGAL RECEIPT ***</p>
    // </div>
        // <div style="font-weight:600; margin-bottom:4px; text-align:center;">CUSTOMER</div>

        // <div style="font-weight:600; margin-bottom:4px; text-align:center;">INVOICE</div>
    