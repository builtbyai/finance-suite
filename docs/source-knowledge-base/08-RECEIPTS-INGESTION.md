# 08 — Receipt Service (Ingestion + Intelligence)

Two sources feed the expense ledger: the **email receipt inbox** (the "email me the digital receipt" UX) and the **Plaid Transactions bank feed** (ground truth). They reconcile against each other so nothing is missed and nothing is double-counted.

## Source 1 — Email receipt inbox (Cloudflare Email Workers + R2)

Cloudflare Email Workers process incoming mail programmatically via an `email()` handler, enabling custom routing. Cloudflare R2 is object storage for unstructured files and integrates natively with Workers. You're already on Cloudflare, so this is a native fit.

### Flow
```
1. PM forwards / bank emails receipt → receipts@example.com
2. Email Worker email() handler fires
3. Worker stores raw .eml + each attachment to R2 (acme-media/receipts/)
4. Worker writes receipts row (status=draft) + enqueues job (Redis on db-host)
5. db-host OCR extracts: merchant, date, total, tax, line items
6. LLM (gpu-host / hosted) classifies Schedule C category + confidence
7. Qdrant dedupe check (vendor+amount+date similarity)
8. Expense draft surfaced in Acme Finance UI
9. User confirms → Ledger.post(expense) → receipts.status=confirmed
10. Expense attaches to PM, customer, project, tax category
```

### Email Worker sketch
```js
export default {
  async email(message, env, ctx) {
    const raw = await streamToArrayBuffer(message.raw, message.rawSize);
    const id = crypto.randomUUID();
    await env.R2.put(`receipts/${id}/raw.eml`, raw);
    // extract + store attachments to R2 under receipts/${id}/att-*
    await env.QUEUE.send({ receipt_id: id, from: message.from });
  }
}
```

> Keep the Worker thin: store + enqueue only. OCR/LLM run on db-host/gpu-host where your pipeline already lives.

## Source 2 — Plaid Transactions (bank feed truth)

Plaid Transactions provides categorized transaction data for syncing, categorization, and reconciliation. This is the authoritative record of what actually cleared the bank.

### Flow
```
1. /transactions/sync (cursor-based) pulls new/modified/removed txns
2. Upsert into bank_transactions (dedupe on plaid_txn_id)
3. Reconciler matches bank_transactions ↔ receipts
     (amount + date window + merchant fuzzy match via Qdrant)
4. Matched: receipt.status=reconciled, link matched_receipt_id
5. Unmatched bank debit with no receipt → flag "missing receipt"
6. Unmatched receipt with no bank txn → likely cash/credit; keep as standalone expense
```

## OCR + classification contract

OCR output normalized to:
```json
{
  "merchant": "Home Depot #6543",
  "txn_date": "2026-03-14",
  "total_cents": 14237,
  "tax_cents": 1087,
  "line_items": [{ "desc": "OSB sheathing", "qty": 12, "amount_cents": 9600 }],
  "payment_last4": "1234"
}
```
LLM adds:
```json
{ "tax_category": "materials", "confidence": 0.94,
  "suggested_project_id": "UUID", "suggested_customer_id": "UUID" }
```

### Confidence policy
- `confidence ≥ 0.90` → pre-fill, one-tap confirm.
- `0.70–0.90` → pre-fill, require review.
- `< 0.70` → manual categorization required.

Never auto-post to the ledger without human confirmation at launch; confidence only controls how much is pre-filled.

## Dedupe (Qdrant)

Embed `merchant + total + date` and check cosine similarity against recent receipts to catch duplicate forwards / re-sends before creating a second draft.

## Attachments & retention

- Keep raw `.eml` and original attachments in R2 (audit trail).
- Retain receipt records ≥ 4 years (IRS recordkeeping guidance).
- R2 keys recorded on `receipts.r2_key` / `raw_email_key` and indexed in the CPA packet.

## Acceptance Criteria

- [ ] Email Worker only stores + enqueues (no OCR/LLM in the Worker).
- [ ] Every emailed receipt produces a `receipts` row with raw `.eml` archived in R2.
- [ ] A duplicate forward of the same receipt does not create a second draft (Qdrant dedupe).
- [ ] Bank debits with no matching receipt are flagged "missing receipt."
- [ ] No receipt posts to the ledger without explicit user confirmation.

Read next: [`09-MILEAGE-EXPENSES.md`](./09-MILEAGE-EXPENSES.md)
