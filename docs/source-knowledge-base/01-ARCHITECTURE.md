# 01 — Architecture

## Service decomposition

Seven services. Each is a logical boundary (module or microservice — your call on deployment granularity). All write to the same Postgres instance on `db-host`; only the **Ledger Service** may write money rows.

| Service | Responsibility | Talks to |
|---|---|---|
| **Billing Service** | PayPal invoices, deposits, invoice status, customer balances | PayPal Invoicing API |
| **Ledger Service** | Immutable money records — the only writer of `ledger_entries` | Postgres |
| **Payout Service** | PM payout eligibility, approval, execution, failure handling | Dwolla, Ledger |
| **Bank Link Service** | Plaid Link, Plaid Auth, Dwolla funding-source creation | Plaid, Dwolla |
| **Tax Service** | W-9 capture, 1099 eligible totals, year-end summaries, e-file export | Tax1099 / Track1099 / IRIS |
| **Receipt Service** | Email ingestion, OCR, attachment storage, AI classification | CF Email Workers, R2, OCR (db-host) |
| **Merch Service** | Storefront products, POD routing, COGS, margin | Printify / Printful API |

## Deployment mapping (reference topology)

| Component | Host | Notes |
|---|---|---|
| API orchestration (Flask) | **Railway** | Stateless; holds provider SDK clients |
| Ledger / app DB (Postgres) | **db-host** (dedicated Linux server) | System of record |
| Receipt OCR + embeddings | **db-host** | Reuse existing OCR pipeline |
| Queue / cache (Redis) | **db-host** | Receipt + payout job queues |
| Vector store (Qdrant) | **db-host** | Receipt/vendor similarity, dedupe |
| LLM classification | **gpu-host** (GPU workstation) or hosted | Receipt categorization, tax tagging |
| Email ingestion | **Cloudflare Email Workers** | `receipts@example.com` catch-all |
| Object storage | **Cloudflare R2** (`acme-media`) | Receipt + statement attachments |
| Frontend (PM payout UI, storefront) | **React/JSX** | custom design system |

## Provider boundary rule

The Flask layer owns all provider SDK calls. No frontend code ever calls Plaid/Dwolla/PayPal/Tax1099 directly. Plaid `link_token` and Dwolla client tokens are minted server-side and handed to the browser short-lived.

## Core sequence: customer invoice → PM payout

```
1.  Acme Finance → PayPal:    create invoice (draft)
2.  Acme Finance → PayPal:    send invoice  → PayPal emails payable link
3.  Customer → PayPal:    pays (PayPal balance / card / guest)
4.  PayPal → Acme Finance:    webhook INVOICING.INVOICE.PAID
5.  Billing → Ledger:     post payment entry (Dr cash, Cr A/R)
6.  Billing → Payout:     mark job revenue realized
7.  Payout:               compute PM eligibility (commission rules)
8.  Operator:             approves payout batch
9.  Payout → Dwolla:      create transfer (source: Acme Finance funding, dest: PM funding source)
10. Dwolla → Acme Finance:    webhook transfer_completed / transfer_failed
11. Payout → Ledger:      post payout entry (Dr payout expense, Cr cash)
12. Payout → Tax:         increment PM YTD paid total
13. Tax:                  flag PM if YTD ≥ 1099 threshold
```

## Core sequence: PM bank linking (the authorization moment)

```
1.  PM → Acme Finance:        opens Payout Setup
2.  Acme Finance → Plaid:     /link/token/create  → link_token
3.  PM → Plaid Link:      logs into bank, selects account
4.  Plaid → Acme Finance:     onSuccess → public_token
5.  Acme Finance → Plaid:     /item/public_token/exchange → access_token
6.  Acme Finance → Plaid:     /processor/token/create (processor=dwolla)
7.  Acme Finance → Dwolla:    create customer (if new)
8.  Acme Finance → Dwolla:    create funding source from processor_token
9.  PM → Acme Finance:        agrees to payout authorization text
10. Acme Finance → Postgres:  store authorization record (ts, IP, UA, last-4)
11. Status:               pending → verified → active
```

## Idempotency & reliability

- Every provider-mutating call carries an **idempotency key** (PayPal `PayPal-Request-Id`, Dwolla `Idempotency-Key`).
- All inbound webhooks are **verified** (signature/cert) and **deduped** by event ID before processing.
- Payout execution is a **two-phase** operation: reserve in ledger → call Dwolla → confirm on webhook. A transfer never posts to the ledger as settled until Dwolla confirms.
- Failed transfers (`transfer_failed`, R-codes) reverse the reservation and surface to the operator.

## Acceptance Criteria

- [ ] No frontend bundle contains a Plaid/Dwolla/PayPal secret or makes a direct provider call.
- [ ] Replaying any webhook event ID twice produces exactly one ledger effect.
- [ ] A payout cannot post as settled without a corresponding Dwolla `transfer_completed` event.

Read next: [`02-DATA-MODEL.md`](./02-DATA-MODEL.md)
