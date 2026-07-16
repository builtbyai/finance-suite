# 00 — Overview

## What we are actually building

QuickBooks is not a "bank account form plus a send button." It is six stacked capabilities. To replace it inside Acme Finance, we replicate each one with a provider that handles the regulated parts so Acme Finance never becomes a money transmitter.

| # | QuickBooks capability | Acme Finance equivalent |
|---|---|---|
| 1 | Bank connection & verification | Plaid Link + Plaid Auth |
| 2 | ACH authorization (legal consent) | Stored authorization record + consent text |
| 3 | Tokenized bank storage | Dwolla funding source ID (no raw numbers) |
| 4 | Money movement | PayPal (in) + Dwolla ACH (out) |
| 5 | Accounting ledger | Postgres double-entry ledger (db-host) |
| 6 | Tax reporting | W-9, 1099 tracking, Tax1099/Track1099/IRIS |

The thing being requested most directly — "what lets it collect bank/routing and send a payment" — is **Plaid Auth (authorization) + Dwolla (movement) + a stored payout-authorization record (consent)**.

## Scope (in)

- Customer invoicing and payment reconciliation
- Project-manager (PM) onboarding, bank linking, payout authorization
- ACH direct-deposit payouts to PMs
- Immutable accounting ledger across invoices, payouts, fees, refunds, expenses, mileage
- Receipt and bank-statement ingestion → OCR → AI classification → ledger
- Mileage and driving-hour logging tied to customer/project/tax year
- W-9 collection, 1099 eligibility tracking, e-file integration, Schedule C export
- Merch storefront with print-on-demand fulfillment routing

## Scope (out / non-goals)

- **Acme Finance is not a money transmitter.** All money movement rides on a licensed provider's rails (PayPal, Dwolla).
- **No auto-filing of income tax returns.** We produce filing-ready packets; a CPA or licensed e-file partner files.
- **No raw bank-number storage** in the application database. Store provider tokens + last-4 only (see `11-COMPLIANCE-SECURITY.md`).
- **No customer ACH debit at launch.** Pulling money from a customer's account triggers stricter NACHA WEB-debit validation rules. Customers pay via PayPal. ACH debit is a later, gated feature.

## Why this stack (and not Stripe)

Stripe Connect collapses payouts + 1099 into one vendor, but it makes Stripe the center of the money system. The decision here is to keep providers as swappable rails so Acme Finance owns orchestration. PayPal stays for inbound because customers already trust PayPal invoices; Dwolla handles outbound ACH cleanly via a Plaid processor-token handoff; 1099 filing is a dedicated, replaceable provider.

## Money-flow summary

```
Customer ──PayPal Invoice──▶ Acme Finance Billing
                                  │ webhook: PAID
                                  ▼
                            Ledger (credit revenue, debit cash)
                                  │ compute PM payout eligibility
                                  ▼
PM (Plaid-linked bank) ◀──Dwolla ACH credit── Payout Service
                                  │
                                  ▼
                            Ledger (debit payout, credit cash)
                                  │ accumulate per-PM YTD
                                  ▼
                            Tax Service (1099 eligibility @ $2,000)
```

## The compliance line, restated

Everything in this knowledge base is buildable. The only non-negotiable boundaries:

1. Money movement always goes through a licensed provider.
2. Raw bank numbers never touch the app DB.
3. Income tax returns are never auto-filed by Acme Finance.

Read next: [`01-ARCHITECTURE.md`](./01-ARCHITECTURE.md)
