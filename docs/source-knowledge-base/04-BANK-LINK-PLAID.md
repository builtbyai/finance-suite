# 04 — Bank Link Service (Plaid)

This is the **authorization layer** — the literal answer to "what lets it collect bank/routing." Plaid Auth retrieves and verifies the account + routing number for checking/savings/cash-management accounts so an app can initiate ACH, and the verified data is handed to Dwolla as a **processor token** so Acme Finance never touches raw bank numbers.

## Two Plaid products, two jobs

| Product | Job | Used in |
|---|---|---|
| **Plaid Auth** | Verify account + return ACH numbers / processor token | PM bank linking (this file) |
| **Plaid Transactions** | Pull categorized bank feed | Reconciliation (`08-RECEIPTS-INGESTION.md`) |

## The Dwolla handoff (why Acme Finance stays clean)

Plaid + Dwolla have a **Secure Exchange** integration: instead of `/auth/get` returning raw numbers to you, you mint a **processor token** scoped to Dwolla. Dwolla creates the funding source from that token. Acme Finance stores only the resulting Dwolla `funding_source_id` + bank last-4. No routing/account numbers ever land in Postgres.

## Link flow (server + client)

### 1. Create link token (server)
```
POST https://production.plaid.com/link/token/create
{
  "user": { "client_user_id": "<pm_user_id>" },
  "client_name": "Acme Finance",
  "products": ["auth"],
  "country_codes": ["US"],
  "language": "en"
}
→ { "link_token": "link-prod-..." }
```

### 2. Open Plaid Link (client)
Frontend opens Link with the `link_token`. PM logs into their bank and selects an account. On success Plaid returns a `public_token` and `account_id` to `onSuccess`.

### 3. Exchange + processor token (server)
```
POST /item/public_token/exchange   { "public_token": "..." }
→ { "access_token": "access-prod-...", "item_id": "..." }

POST /processor/token/create
{ "access_token": "access-prod-...",
  "account_id": "<selected account>",
  "processor": "dwolla" }
→ { "processor_token": "processor-prod-..." }
```

### 4. Hand to Dwolla (server)
Pass `processor_token` to Dwolla funding-source creation — see `05-PAYOUTS-DWOLLA.md`. Persist Dwolla `funding_source_id` + bank metadata to `pm_payout_profiles`.

## Verification coverage

Plaid Auth supports several verification paths. Order of preference:

1. **Instant Auth (OAuth login)** — fastest, real bank connection. Some institutions return a **tokenized account number (TAN)** usable by any ACH processor.
2. **Instant Micro-deposits (RTP/FedNow)** — user verifies a code in ~seconds.
3. **Database Match** — instant, no micro-deposits; verifies ~30% of accounts against Plaid's known-account network.
4. **Same-Day Micro-deposits** — fallback; user confirms a deposit code in ~1 business day.

Listen for the `AUTH` webhook (`AUTOMATICALLY_VERIFIED` / `VERIFICATION_EXPIRED`) for micro-deposit flows; flip `pm_payout_profiles.status` accordingly.

## Risk add-ons (optional, recommended)

- **Balance** — confirm funds exist before debits (not needed for credits/payouts).
- **Signal** — ML risk score for ACH return likelihood.
- **Identity** — confirm account ownership name matches W-9 legal name (cross-check before activating payout).

## State machine: `pm_payout_profiles.status`

```
pending ──(processor token + Dwolla FS created)──▶ verified
verified ──(authorization signed + identity match)──▶ active
verified ──(micro-deposit expired / mismatch)──▶ failed
active ──(operator/PM disable)──▶ disabled
```

## What Acme Finance stores vs. never stores

| Store | Never store |
|---|---|
| Dwolla `funding_source_id` | Full account number |
| Dwolla `customer_id` | Full routing number |
| `bank_last4`, `bank_name`, `account_type` | Plaid `access_token` in plaintext (encrypt at rest, scope tightly) |
| Plaid `item_id` | — |

## Acceptance Criteria

- [ ] No raw account/routing number is ever returned to Acme Finance servers in the payout flow (processor-token path only).
- [ ] A profile reaches `active` only after both authorization signature and identity/name check pass.
- [ ] Micro-deposit verification webhooks correctly transition `status`.
- [ ] Plaid `access_token` is encrypted at rest.

Read next: [`05-PAYOUTS-DWOLLA.md`](./05-PAYOUTS-DWOLLA.md)
