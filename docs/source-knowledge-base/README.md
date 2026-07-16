# Acme Finance Suite — Build Knowledge Base

> **Self-owned ledger. Providers as rails.**
> A QuickBooks-equivalent finance system embedded inside Acme Finance — without making Stripe or QuickBooks the center of the system.

This knowledge base specifies a self-owned billing, payout, receipt, and tax suite. Acme Finance owns the workflow, customer context, project context, PM payout logic, receipt intelligence, and tax-ready ledger. External providers are used only as **rails**, never as the system of record.

---

## The non-Stripe stack (decision locked)

| Function | Provider | Role |
|---|---|---|
| Customer invoicing | **PayPal Invoicing API** | Inbound customer money |
| Bank authorization | **Plaid Auth / Link** | Verify + tokenize PM bank accounts |
| ACH payouts | **Dwolla** | Outbound direct deposit to PMs |
| 1099 filing | **Tax1099 / Track1099 / IRS IRIS** | W-9, TIN match, e-file |
| Receipt ingestion | **Cloudflare Email Workers + R2** | Email → object store → OCR |
| Bank feed truth | **Plaid Transactions** | Reconciliation source |
| Merch fulfillment | **Printify / Printful API** | Print-on-demand storefront |
| System of record | **Postgres (db-host)** | Immutable ledger |

---

## File index

| File | Scope |
|---|---|
| [`00-OVERVIEW.md`](./00-OVERVIEW.md) | The QuickBooks-equivalence model, scope, non-goals, the hard compliance line |
| [`01-ARCHITECTURE.md`](./01-ARCHITECTURE.md) | Services, fleet mapping, sequence flows |
| [`02-DATA-MODEL.md`](./02-DATA-MODEL.md) | Full Postgres schema for every table |
| [`03-BILLING-PAYPAL.md`](./03-BILLING-PAYPAL.md) | PayPal Invoicing integration + webhook reconciliation |
| [`04-BANK-LINK-PLAID.md`](./04-BANK-LINK-PLAID.md) | Plaid Link → Auth → Dwolla processor-token handoff |
| [`05-PAYOUTS-DWOLLA.md`](./05-PAYOUTS-DWOLLA.md) | Dwolla customers, funding sources, transfers, failures |
| [`06-LEDGER-SERVICE.md`](./06-LEDGER-SERVICE.md) | Double-entry immutable ledger |
| [`07-TAX-1099.md`](./07-TAX-1099.md) | W-9, TIN match, 2026 thresholds, e-file, Schedule C export |
| [`08-RECEIPTS-INGESTION.md`](./08-RECEIPTS-INGESTION.md) | Email Workers + R2 + db-host OCR + AI classification |
| [`09-MILEAGE-EXPENSES.md`](./09-MILEAGE-EXPENSES.md) | Mileage logs, rate table, expense model |
| [`10-MERCH-FULFILLMENT.md`](./10-MERCH-FULFILLMENT.md) | POD API, local DFW, China sourcing |
| [`11-COMPLIANCE-SECURITY.md`](./11-COMPLIANCE-SECURITY.md) | Consent language, NACHA, tokenization, data handling |
| [`12-BUILD-ORDER.md`](./12-BUILD-ORDER.md) | Phased roadmap with executable acceptance criteria |

---

## How to use this with your agent loop

Each service file ends with an **Acceptance Criteria** block written as executable assertions. Feed `12-BUILD-ORDER.md` as the spec entrypoint to your generate-verify-critique-repair loop; each phase's acceptance criteria are the verifier's pass/fail gate.

## The one hard line

Build everything **up to** the tax return. Generate 1099 information returns, categorize to Schedule C, produce CPA-ready packets. **Do not auto-file income tax returns** — that is a regulated act and stays with a CPA or licensed e-file partner.
