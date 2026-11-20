# Pergamon VFD integration (draft — requires provider response confirmation)

## API reference supplied on 20 Nov 2026
Bruno/OpenCollection HTML collection: `GET /invoices`, `GET /invoices/{id}`, `GET /periodic-reports?from=YYYY-MM-DD&to=YYYY-MM-DD`, `POST /generate-invoices` and `POST /invoices` (receipt creation). Uses HTTP Basic Authentication. The attachment contained a credential: **do not commit or publish it; rotate the credential with Pergamon before going live**. The example host was deliberately not hardcoded.

## Setup (v15-hotfix)
1. Migrate on a Frappe 15 development site to create `Pergamon VFD Settings` and the `Pergamon` VFD Provider registration.
2. Create `Pergamon VFD Settings` for each company with HTTPS API Base URL, username, **Password** field, start date, default payment type, and preview preference.
3. Select `Pergamon` in the existing `Company VFD Provider` link for that company.
4. On a *submitted* Sales Invoice, use the existing Generate VFD button. Review preview; send only after verifying the outgoing tax and gross figures.
5. Pending or ambiguous responses **must be reconciled manually** through Pergamon before any retry. Do not clear Pending without evidence.

## Receipt mapping
- Sales Invoice name -> `traderInvoiceNo`, company-scoped number
- Customer identification -> `custIdType` and `custId`; name/phone -> `custName`/`custPhone`
- Invoice `posting_date`/`posting_time` -> `dateTime`
- Per-line VAT-inclusive base amount -> `salesItems[].amount`; name, quantity, unit price and VFD tax code -> salesItems fields
- Invoice gross total -> `totalAmount`, default payment type -> `paymentType`, TZS and 1.0 exchange rate.

The alternate flat `POST /generate-invoices` request is **not** used; its schema cannot represent itemized tax codes. Tax code mapping A–E follows the app's existing mapping but must be confirmed with Pergamon. Non-TZS is blocked until the provider's currency contract is confirmed.

## Provider response contract still missing
The supplied reference has no response body, status/error semantics, receipt number, receipt verification URL or guaranteed idempotency behavior. Current adapter marks Success only when a candidate receipt identifier (rctvnum, verificationCode, receiptNumber) appears; **these are provisional aliases** pending a real test response. All other outcomes remain Pending, including HTTP 200 with no fiscal identifier. Do not claim TRA issuance from an HTTP code alone.

**Important**: The existing scheduler can find Pending invoices; adapter refuses to repost them. Reconcile against `GET /invoices` (and `GET /invoices/{id}` when Pergamon ID is known), then complete a manual corrective workflow when supported. An API timeout leaves persisted Pending intent. No blind auto-retry.

## UAT matrix (must be done before ready-to-merge)
- Successful receipt: inspect real response, verification number/URL, and receipt print rendering
- 400/401/403/500/timeouts, invalid JSON, and duplicate request
- Two companies use different credentials and URL
- Duplicate manual + scheduler execution, unresolved Pending, and double-click
- Tax templates A/B/C/D/E, invoice discounts/rounding, credit notes and cancel behavior
- Foreign-currency invoice blocked; backdated invoice blocked
- Preview/submit, authenticated access, logging redaction, TLS certificate validation
- Migration and rollback on Frappe 15 and a separate upgrade plan for Frappe 16

## Navigation & analytics audit
The v15 branch has `config/desktop.py` and two modules (`VFD Providers`, `VFD Settings`) but no native Dock/Sidebar/Workspace/Number Card/Chart/Dashboard exports. No schema-verified development-site export is available. New settings remain accessible via native DocType search; app navigation/analytics is **blocked** for the feature-completion gate, not falsely marked complete. Suggested KPI: VFD Provider Posting count by response status and company, but the posting DocType currently lacks a company field and definitive provider success semantics. Do not create a misleading metric. Build role-safe exports from a real supported Frappe site.

## Branch note
`version-16-hotfix` currently has only the minimal app skeleton, not the v15 provider DocTypes/controllers. This feature targets `version-15-hotfix` and is **not** a direct v16 backport until the underlying provider framework is ported.
