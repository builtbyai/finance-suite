# BUILD-SPEC — Local Execution Plan

This file is the actionable plan, derived from `docs/source-knowledge-base/12-BUILD-ORDER.md`.
**Dependency rule:** Ledger → Payouts. Authorization → Movement. Totals → Filing.

## Phase 0 — Project scaffold ✅
- Backend (Flask), frontend (Vite/React), SQLite local DB, env config, seed script.

## Phase 1 — Customer invoicing ✅
- `services/billing.py` — PayPal Invoicing client (OAuth2 cached token, create/send/cancel/refund/get).
- `routes/invoices.py` — `POST /api/invoices`, `POST /api/invoices/:id/send`, `GET /api/invoices`.
- Models: `customers`, `invoices`.

**Acceptance:** an invoice can be created and tracked. PayPal call is live when `PAYPAL_CLIENT_ID/SECRET` set; otherwise a `PayPalClient.dry_run=True` mode records the same DB state without an outbound call.

## Phase 2 — Invoice webhook reconciliation ✅
- `routes/webhooks.py` — `POST /api/webhooks/paypal` with signature verify, dedupe via `webhook_events`.
- Nightly fallback poll job (`scripts/reconcile_invoices.py`).

**Acceptance:** an invoice flips to `paid` only via verified webhook OR the polling reconciler. Duplicate event → single ledger effect.

## Phase 3 — Ledger (foundation) ✅
- `services/ledger.py`:
  - `Ledger.post(entry_type, occurred_at, lines, ...)` — validates `Σdebit == Σcredit`, append-only.
  - `Ledger.balance(code, as_of=None)`.
  - `Ledger.pm_ytd_paid(pm_user_id, year)`.
  - `Ledger.pnl(start, end)`.
  - `Ledger.reserve(payout_id, amount)` → pending reservation, settled only on Dwolla webhook.
- DB-level invariant: trigger that rejects unbalanced entries on commit.

**Acceptance:** every `post()` balances or raises. No `UPDATE/DELETE` on `ledger_entries` / `ledger_lines`.

## Phase 4 — PM payout profile + W-9 ✅
- Models: `pm_payout_profiles`, `payout_authorizations`, `w9_records`.
- `services/tax.py` — W-9 capture (last-4 only), `w9_status` state machine.
- `routes/payouts.py` — `POST /api/payouts/profile`, `POST /api/payouts/profile/:id/w9`, `POST /api/payouts/profile/:id/authorize`.

**Acceptance:** a PM completes payout setup; W-9 stored with last-4 only; authorization record captures ts/IP/UA/text-hash.

## Phase 5 — Plaid + Dwolla bank payout ✅
- `services/bank_link.py` — Plaid Link token mint, public-token exchange, processor-token creation.
- `services/payout.py` — Dwolla customer + funding-source from processor token; two-phase transfer with `Idempotency-Key`; ACH return code handling.
- `routes/webhooks.py` — Plaid + Dwolla webhook handlers (HMAC verify, dedupe).

**Acceptance:** payout settles in ledger ONLY on `transfer_completed`. Failures reverse the reservation. No raw bank numbers stored.

## Phase 6 — 1099 tracking ✅
- `tax_thresholds` seeded with 2025 ($600) + 2026 ($2,000) NEC/MISC.
- `services/tax.py:compute_1099_eligibility()` — reads ledger YTD per PM.
- Double-reporting guard via `payouts.provider`.

**Acceptance:** YTD per PM matches `SUM(payouts.amount WHERE status=completed AND year=Y)`. Eligibility flips at threshold.

## Phase 7 — Receipt inbox ✅
- `services/receipt.py` — `POST /api/receipts` (multipart upload), draft → confirmed → reconciled.
- Email Worker reference in `docs/source-knowledge-base/08-RECEIPTS-INGESTION.md` (Cloudflare-deployable, out of scope for local Flask).

**Acceptance:** an uploaded receipt creates a draft row; confirming posts a ledger expense entry.

## Phase 8 — Bank feed reconciliation 🟡
- `services/bank_link.py:sync_transactions()` — calls Plaid `/transactions/sync`, upserts `bank_transactions`, runs match logic against receipts.

**Acceptance:** unmatched debits flagged `missing_receipt=true`.

## Phase 9 — Mileage logs ✅
- `mileage_rates` table seeded (2025: 70¢, 2026: 70¢ — verify before season).
- `services/mileage.py:log_trip()` — snapshots rate onto row at insert.
- Memo ledger entry hits `vehicle_expense` not cash.

**Acceptance:** changing a year's rate does not alter past logs.

## Phase 10 — Tax packet export ✅
- `services/tax.py:export_schedule_c(year)` — returns JSON + CSV (PDF stub).
- Per-PM 1099 totals + W-9 status + TIN-match status.

**Acceptance:** packet maps every expense line to a `tax_category`.

## Phase 11 — Merch fulfillment ✅
- `services/merch.py` — `FulfillmentProvider` protocol with `Printful`, `Printify`, `Local`, `China` implementations (HTTP clients; `dry_run` mode for local).
- Order → ledger posts both revenue and COGS.

**Acceptance:** a merch sale posts revenue + COGS with margin.

---

## Verifier gate

Every phase has unit tests in `backend/tests/`. Run:

```bash
cd backend && pytest -q
```

E2E smoke (frontend reachable, dashboard renders, can create invoice):

```bash
npx playwright test e2e/smoke.spec.js
```
