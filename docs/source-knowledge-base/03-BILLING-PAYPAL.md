# 03 — Billing Service (PayPal Invoicing)

PayPal handles **inbound customer money** only. Customers already understand PayPal invoices, so this is the lowest-friction inbound rail. Acme Finance creates and tracks invoices; PayPal emails the payable link and collects payment.

## Why PayPal here (and its limits)

- **Invoicing API** creates, sends, manages, and tracks invoices. When sent, PayPal emails the customer a payable link; the customer pays via PayPal balance, card, or guest checkout.
- **Not for PM payouts.** PayPal Standard Payouts pay to PayPal/Venmo accounts, not to a routing+account number you collected, and the Payouts API is not part of the standard PayPal SDK. PM direct deposit is handled by Dwolla — see `05-PAYOUTS-DWOLLA.md`.

## Auth

OAuth2 client-credentials. Mint an access token server-side and cache until expiry.

```
POST https://api-m.paypal.com/v1/oauth2/token
grant_type=client_credentials
Authorization: Basic base64(client_id:secret)
```

Required scope includes `https://uri.paypal.com/services/invoicing`.

## Invoice lifecycle

| Step | Endpoint | Notes |
|---|---|---|
| Create draft | `POST /v2/invoicing/invoices` | Returns invoice `id` + `href` |
| Generate number | `POST /v2/invoicing/generate-next-invoice-number` | Or supply your own |
| Send | `POST /v2/invoicing/invoices/{id}/send` | Triggers customer email |
| Get | `GET /v2/invoicing/invoices/{id}` | Status polling fallback |
| Cancel | `POST /v2/invoicing/invoices/{id}/cancel` | |
| Record refund | `POST /v2/invoicing/invoices/{id}/refunds` | Mirrors to ledger |

Always send `PayPal-Request-Id` (idempotency) on create.

### Minimal create body

```json
{
  "detail": {
    "currency_code": "USD",
    "invoice_number": "INV-2026-0001",
    "reference": "project_id:UUID"
  },
  "primary_recipients": [
    { "billing_info": { "email_address": "customer@example.com" } }
  ],
  "items": [
    { "name": "Roof replacement — claim work",
      "quantity": "1",
      "unit_amount": { "currency_code": "USD", "value": "9850.00" } }
  ]
}
```

## Webhook reconciliation (the critical part)

Acme Finance must learn of payment from PayPal, not from the customer saying so. Subscribe to:

| Event | Action |
|---|---|
| `INVOICING.INVOICE.PAID` | Mark invoice `paid`, post ledger payment entry, trigger payout eligibility |
| `INVOICING.INVOICE.PARTIALLY_PAID` | Mark `partially_paid`, post partial entry |
| `INVOICING.INVOICE.CANCELLED` | Mark `cancelled` |
| `INVOICING.INVOICE.REFUNDED` | Post reversing ledger entry |
| `PAYMENT.CAPTURE.REFUNDED` | Reconcile refund |

### Webhook handling rules

1. **Verify signature** via `POST /v1/notifications/verify-webhook-signature` (or cert chain). Reject if invalid.
2. **Dedupe** on `webhook_events (provider='paypal', event_id)`.
3. **Process once**, then set `processed_at`.
4. On `PAID`: call Ledger Service to post `Dr cash / Cr accounts_receivable`, record `processor_fees` as a separate line if known.

### Reconciliation flow

```
PayPal webhook PAID
  → verify signature
  → dedupe by event_id
  → invoices.status = 'paid', paid_at = now()
  → Ledger.post(entry_type='invoice_payment',
        lines=[Dr cash, Cr ar, Dr processor_fees/Cr cash])
  → Payout.on_revenue_realized(project_id)
```

## Failure & edge handling

- **Webhook missed?** Nightly job polls `GET /v2/invoicing/invoices?status=SENT` older than N days and reconciles.
- **Overpayment / currency mismatch:** post the actual captured amount from the event, not the invoice face value.
- **Disputes/chargebacks:** subscribe to `CUSTOMER.DISPUTE.CREATED`; freeze any downstream PM payout tied to that project until resolved.

## Acceptance Criteria

- [ ] An invoice is only marked `paid` by a verified, deduped `INVOICING.INVOICE.PAID` webhook (never by client action).
- [ ] Every paid invoice produces exactly one balanced ledger entry.
- [ ] A missed webhook is recovered by the nightly polling job within 24h.
- [ ] Processor fees are posted as a distinct ledger line, not netted silently.

Read next: [`04-BANK-LINK-PLAID.md`](./04-BANK-LINK-PLAID.md)
