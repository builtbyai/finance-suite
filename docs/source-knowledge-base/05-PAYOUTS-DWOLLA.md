# 05 — Payout Service (Dwolla ACH)

Dwolla is the **outbound money rail** — direct ACH deposit to PM bank accounts. This delivers the true QuickBooks-style direct-deposit feature without Stripe. Dwolla supports account-to-account movement including ACH, Same-Day ACH, RTP, and FedNow; its Transfers resource initiates, tracks, cancels, and inspects transfers.

## Object model

```
Dwolla Account (Acme Finance master)
  └── Funding Source (Acme Finance business bank, the source of funds)
Dwolla Customer (one per PM)
  └── Funding Source (PM bank, created from Plaid processor token)
Transfer: source = Acme Finance FS, destination = PM FS
```

## One-time setup

1. Create the Acme Finance **master Dwolla account** (business verification / KYB).
2. Add Acme Finance's **business bank** as a verified funding source (the payout source).
3. Configure webhook subscription + secret.

## PM onboarding (continues from Plaid handoff)

### 1. Create / reuse customer
```
POST /customers
{
  "firstName": "...", "lastName": "...",
  "email": "...",
  "type": "receive-only" | "unverified" | "verified",
  "businessName": "<if entity>"
}
→ Location header = customer URL  → store provider_customer_id
```
> `receive-only` customers can accept payouts with minimal info — good default for PMs who only get paid. Escalate to `verified` if volume/limits require.

### 2. Create funding source from Plaid processor token
```
POST /customers/{id}/funding-sources
{
  "plaidToken": "<processor-token from Plaid>",
  "name": "PM checking ••1234"
}
→ funding source URL → store provider_funding_id + bank_last4
```

### 3. Mark profile `verified` → `active` after authorization signed.

## Executing a payout (two-phase)

Never call Dwolla without first reserving in the ledger; never post settled without the completion webhook.

```
1. Operator approves payout batch
2. Payout.reserve():
     create payouts row (status=pending, idempotency_key=uuid)
     Ledger reservation (pending, not settled)
3. POST /transfers  (Idempotency-Key: <key>)
   {
     "_links": {
       "source":      { "href": "<Acme Finance FS url>" },
       "destination": { "href": "<PM FS url>" }
     },
     "amount": { "currency": "USD", "value": "1450.00" },
     "metadata": { "payout_id": "<uuid>", "pm_user_id": "<uuid>" },
     "clearing": { "destination": "next-day" }   // or "same-day"
   }
   → Location = transfer URL → store provider_transfer_id, status=processing
4. Wait for webhook:
     transfer_completed → payouts.status=completed; Ledger settle
                          (Dr payout_expense / Cr cash); Tax.increment_ytd()
     transfer_failed    → payouts.status=failed; store ACH return code;
                          reverse reservation; alert operator
     transfer_cancelled → reverse reservation
```

## Webhooks

| Event | Action |
|---|---|
| `customer_funding_source_added` | Confirm FS, advance status |
| `transfer_created` | Mark `processing` |
| `transfer_completed` | Settle ledger, increment PM YTD |
| `transfer_failed` | Record return code, reverse, alert |
| `transfer_cancelled` | Reverse reservation |
| `customer_funding_source_removed` | Disable profile |

Verify Dwolla webhook **HMAC signature** with the subscription secret; dedupe by event id in `webhook_events`.

## ACH return codes to handle

| Code | Meaning | Handling |
|---|---|---|
| R01 | Insufficient funds (source) | Retry after funding; alert operator |
| R02 | Account closed | Disable FS, require re-link |
| R03 | No account / unable to locate | Disable FS, require re-link |
| R04 | Invalid account number | Disable FS, require re-link |
| R16 | Account frozen | Hold payouts, alert |
| R20 | Non-transaction account | Require different account |

A failed payout **always reverses** the ledger reservation. The PM's YTD total only increments on `transfer_completed`.

## Clearing / speed

- **Standard ACH:** 3–4 business days.
- **Same-Day ACH:** set `clearing.destination = "same-day"` (cutoff + fee apply).
- **RTP / FedNow:** instant where the receiving bank supports it; gate behind a feature flag.

## Limits & batching

- Group approved payouts into an operator-reviewed batch UI; execute sequentially with per-transfer idempotency keys.
- Respect Dwolla transfer limits for the customer verification tier; escalate `receive-only`→`verified` if a PM exceeds receive limits.

## Acceptance Criteria

- [ ] A payout posts to the ledger as settled **only** on `transfer_completed`.
- [ ] Every `POST /transfers` carries a unique `Idempotency-Key`; retries never double-send.
- [ ] A `transfer_failed` reverses the reservation and records the ACH return code.
- [ ] PM YTD paid total increments exclusively on completion, never on initiation.
- [ ] Re-running the same approved batch produces no duplicate transfers.

Read next: [`06-LEDGER-SERVICE.md`](./06-LEDGER-SERVICE.md)
