# 12 — Build Order

Sequenced so each phase produces a verifiable artifact. Each phase's **acceptance criteria are the verifier gate** for your generate-verify-critique-repair loop — feed this file as the spec entrypoint and let the loop close one phase before opening the next.

## Dependency rule

> **Build the ledger before payouts. Build authorization before money movement. Build 1099-ready totals before filing automation.**

## Phases

### Phase 1 — Customer invoicing (you're close here)
Spec: `03-BILLING-PAYPAL.md`
- PayPal Invoicing create/send/cancel/refund.
- Customer + invoice models.

**Acceptance:** an invoice can be created and sent; PayPal emails a payable link; status reflects in Acme Finance.

### Phase 2 — Invoice webhook reconciliation
Spec: `03-BILLING-PAYPAL.md`, `11-COMPLIANCE-SECURITY.md`
- Verified, deduped PayPal webhooks; nightly polling fallback.

**Acceptance:** invoice flips to `paid` only via verified webhook; replaying an event yields one effect; a missed webhook recovers within 24h.

### Phase 3 — Ledger (foundation)
Spec: `06-LEDGER-SERVICE.md`, `02-DATA-MODEL.md`
- Chart of accounts; `Ledger.post()`; balance trigger; reservations.

**Acceptance:** every entry balances or is rejected; no UPDATE/DELETE on money rows; invoice payments post correctly.

### Phase 4 — PM payout profile + W-9
Spec: `02-DATA-MODEL.md`, `07-TAX-1099.md`
- Payout setup UI (legal name, entity, classification, method, status).
- W-9 capture; store `tin_last4` only.
- **Quick-launch option:** PayPal/Venmo payout method first (PM needs PayPal/Venmo).

**Acceptance:** a PM can complete payout setup; W-9 stored with last-4 only; status machine works.

### Phase 5 — Plaid + Dwolla bank payout (true direct deposit)
Spec: `04-BANK-LINK-PLAID.md`, `05-PAYOUTS-DWOLLA.md`, `11-COMPLIANCE-SECURITY.md`
- Plaid Link → Auth → Dwolla processor token → funding source.
- Two-phase transfer; webhook settlement; ACH return handling.
- Signed payout authorization record.

**Acceptance:** a payout reaches the PM's bank; settles in ledger only on `transfer_completed`; failures reverse; no raw bank numbers stored; idempotent execution.

### Phase 6 — W-9 / 1099 tracking
Spec: `07-TAX-1099.md`
- `tax_thresholds` seeded (2026 NEC/MISC = $2,000); TIN match; eligibility computation.

**Acceptance:** per-PM YTD totals match completed payouts; eligibility flips at the configured threshold; double-reporting guard in place.

### Phase 7 — Receipt inbox
Spec: `08-RECEIPTS-INGESTION.md`
- CF Email Worker → R2 → queue → db-host OCR → LLM classify → confirm → ledger.

**Acceptance:** emailed receipt becomes a confirmed expense entry; raw `.eml` archived; duplicates deduped; nothing posts without confirmation.

### Phase 8 — Bank feed reconciliation
Spec: `08-RECEIPTS-INGESTION.md`
- Plaid Transactions sync; reconcile bank txns ↔ receipts.

**Acceptance:** cleared bank debits match receipts; unmatched debits flagged "missing receipt."

### Phase 9 — Mileage logs
Spec: `09-MILEAGE-EXPENSES.md`
- `mileage_rates` table; rate snapshot per log; attribution to customer/project/year.

**Acceptance:** logs attribute correctly; rate changes never alter past logs; memo entries hit the tax packet not cash.

### Phase 10 — Tax packet output
Spec: `07-TAX-1099.md`
- Schedule C-mapped export (CSV/PDF/JSON); contractor + mileage summaries; attachments index.
- Then: Tax1099/Track1099 e-file integration. (IRIS direct only if volume justifies.)

**Acceptance:** packet maps every expense to a tax category; 1099-ready totals export; (later) 1099s e-file via provider.

### Phase 11 — Merch fulfillment
Spec: `10-MERCH-FULFILLMENT.md`
- Provider-agnostic routing; Printify/Printful API first; local vendor queue; China later.

**Acceptance:** a merch sale posts revenue + COGS with margin; fulfillment mode swappable without storefront changes.

## Milestone summary

| Milestone | Phases | Outcome |
|---|---|---|
| **M1 — Get paid** | 1–3 | Invoice customers, reconcile, ledger truth |
| **M2 — Pay PMs** | 4–6 | Direct-deposit payouts + 1099 tracking |
| **M3 — Books close themselves** | 7–10 | Receipts, reconciliation, mileage, tax packet |
| **M4 — Storefront** | 11 | Merch with margin tracking |

## Loop integration

For each phase: the spec file is the input, the **Acceptance Criteria** block is the executable verifier gate, and the critique-repair cycle runs until every checkbox passes before advancing. Do not let a phase open before its predecessor's gate is green — the dependency rule is load-bearing (ledger before payouts, authorization before movement, totals before filing).
