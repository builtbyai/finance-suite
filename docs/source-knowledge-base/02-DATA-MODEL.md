# 02 — Data Model

Postgres on `db-host`. All money amounts stored as **integer cents** (`BIGINT`), never floats. All timestamps `TIMESTAMPTZ`. UUID primary keys.

## Conventions

- `amount_cents BIGINT NOT NULL` — money is always integer cents.
- `currency CHAR(3) NOT NULL DEFAULT 'USD'`.
- Money rows are **append-only**. Corrections are new reversing entries, never `UPDATE`/`DELETE`.
- `provider_*_id` columns hold external tokens. Raw bank numbers are forbidden.

## Entities

### `pm_payout_profiles`
The PM's payout identity. Stores tokens and last-4 only.

```sql
CREATE TABLE pm_payout_profiles (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pm_user_id             UUID NOT NULL REFERENCES users(id),
  legal_name             TEXT NOT NULL,
  entity_type            TEXT NOT NULL,           -- individual | sole_prop | llc | s_corp | c_corp
  tax_classification     TEXT,                    -- maps to W-9 box
  payout_method          TEXT NOT NULL,           -- ach_bank | paypal | venmo
  provider_name          TEXT,                    -- 'dwolla'
  provider_customer_id   TEXT,                    -- Dwolla customer URL/id
  provider_funding_id    TEXT,                    -- Dwolla funding source id (the token)
  bank_name              TEXT,
  bank_last4             CHAR(4),
  account_type           TEXT,                    -- checking | savings
  status                 TEXT NOT NULL DEFAULT 'pending',  -- pending|verified|active|failed|disabled
  w9_status              TEXT NOT NULL DEFAULT 'not_collected', -- not_collected|collected|tin_verified|tin_mismatch
  is_1099_eligible       BOOLEAN NOT NULL DEFAULT FALSE,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `payout_authorizations`
The legal consent record. Immutable. One active row per profile.

```sql
CREATE TABLE payout_authorizations (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id         UUID NOT NULL REFERENCES pm_payout_profiles(id),
  consent_version    TEXT NOT NULL,               -- e.g. 'pm-payout-v1'
  consent_text_hash  TEXT NOT NULL,               -- sha256 of exact text shown
  authorized_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  ip_address         INET NOT NULL,
  user_agent         TEXT NOT NULL,
  revoked_at         TIMESTAMPTZ
);
```

### `customers`
```sql
CREATE TABLE customers (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT NOT NULL,
  email         TEXT,
  phone         TEXT,
  project_id    UUID REFERENCES projects(id),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `invoices`
```sql
CREATE TABLE invoices (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id         UUID NOT NULL REFERENCES customers(id),
  project_id          UUID REFERENCES projects(id),
  provider            TEXT NOT NULL DEFAULT 'paypal',
  provider_invoice_id TEXT UNIQUE,                 -- PayPal invoice id
  number              TEXT NOT NULL,
  amount_cents        BIGINT NOT NULL,
  currency            CHAR(3) NOT NULL DEFAULT 'USD',
  status              TEXT NOT NULL DEFAULT 'draft', -- draft|sent|paid|partially_paid|cancelled|refunded
  payable_url         TEXT,
  issued_at           TIMESTAMPTZ,
  paid_at             TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `ledger_accounts`
Chart of accounts. Double-entry needs named accounts.

```sql
CREATE TABLE ledger_accounts (
  id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code      TEXT UNIQUE NOT NULL,   -- e.g. 'cash', 'ar', 'revenue', 'payout_expense', 'processor_fees'
  name      TEXT NOT NULL,
  type      TEXT NOT NULL           -- asset|liability|equity|revenue|expense
);
```

### `ledger_entries` + `ledger_lines`
Append-only journal. An **entry** is a balanced transaction; **lines** are its debits/credits.

```sql
CREATE TABLE ledger_entries (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entry_type      TEXT NOT NULL,    -- invoice_payment|payout|fee|refund|expense|mileage|adjustment
  source_table    TEXT,             -- 'invoices' | 'payouts' | 'expenses' ...
  source_id       UUID,
  memo            TEXT,
  occurred_at     TIMESTAMPTZ NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  reverses_entry  UUID REFERENCES ledger_entries(id)  -- for corrections
);

CREATE TABLE ledger_lines (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entry_id      UUID NOT NULL REFERENCES ledger_entries(id),
  account_id    UUID NOT NULL REFERENCES ledger_accounts(id),
  direction     TEXT NOT NULL,      -- debit | credit
  amount_cents  BIGINT NOT NULL CHECK (amount_cents > 0),
  pm_user_id    UUID REFERENCES users(id),     -- attribution
  customer_id   UUID REFERENCES customers(id),
  project_id    UUID REFERENCES projects(id),
  tax_category  TEXT                            -- Schedule C line mapping
);
-- INVARIANT: SUM(debit) = SUM(credit) per entry_id. Enforce in app + a constraint trigger.
```

### `payouts`
```sql
CREATE TABLE payouts (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id          UUID NOT NULL REFERENCES pm_payout_profiles(id),
  pm_user_id          UUID NOT NULL REFERENCES users(id),
  amount_cents        BIGINT NOT NULL,
  provider            TEXT NOT NULL DEFAULT 'dwolla',
  provider_transfer_id TEXT UNIQUE,
  idempotency_key     TEXT UNIQUE NOT NULL,
  status              TEXT NOT NULL DEFAULT 'pending', -- pending|processing|completed|failed|cancelled
  failure_code        TEXT,            -- ACH return code (R01, R02, ...)
  approved_by         UUID REFERENCES users(id),
  approved_at         TIMESTAMPTZ,
  initiated_at        TIMESTAMPTZ,
  completed_at        TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `w9_records`
```sql
CREATE TABLE w9_records (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id      UUID NOT NULL REFERENCES pm_payout_profiles(id),
  provider        TEXT,             -- 'tax1099' | 'track1099'
  provider_ref    TEXT,             -- external record id
  tin_last4       CHAR(4),
  tin_match_status TEXT,            -- pending|match|mismatch|foreign
  collected_at    TIMESTAMPTZ,
  document_r2_key TEXT              -- stored W-9 PDF in R2
);
```

### `receipts`
```sql
CREATE TABLE receipts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source          TEXT NOT NULL,     -- email | upload | bank_feed
  r2_key          TEXT,              -- attachment in R2
  raw_email_key   TEXT,              -- original .eml in R2
  merchant        TEXT,
  total_cents     BIGINT,
  tax_cents       BIGINT,
  txn_date        DATE,
  category        TEXT,              -- AI-classified Schedule C category
  confidence      NUMERIC(4,3),
  pm_user_id      UUID REFERENCES users(id),
  customer_id     UUID REFERENCES customers(id),
  project_id      UUID REFERENCES projects(id),
  status          TEXT NOT NULL DEFAULT 'draft', -- draft|confirmed|rejected|reconciled
  ledger_entry_id UUID REFERENCES ledger_entries(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `bank_transactions`
Plaid Transactions feed for reconciliation.

```sql
CREATE TABLE bank_transactions (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plaid_account_id  TEXT NOT NULL,
  plaid_txn_id      TEXT UNIQUE NOT NULL,
  amount_cents      BIGINT NOT NULL,
  name              TEXT,
  category          TEXT,
  posted_date       DATE,
  pending           BOOLEAN,
  matched_receipt_id UUID REFERENCES receipts(id),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `mileage_logs`
```sql
CREATE TABLE mileage_logs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  driver_user_id  UUID NOT NULL REFERENCES users(id),
  vehicle         TEXT,
  start_location  TEXT,
  end_location    TEXT,
  miles           NUMERIC(8,2) NOT NULL,
  minutes         INTEGER,
  purpose         TEXT,
  customer_id     UUID REFERENCES customers(id),
  project_id      UUID REFERENCES projects(id),
  lead_id         UUID,
  reimbursement_status TEXT DEFAULT 'unreimbursed',
  tax_year        INTEGER NOT NULL,
  rate_cents      INTEGER,          -- snapshot of rate used (cents per mile)
  deduction_cents BIGINT,           -- miles * rate at log time
  logged_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `mileage_rates`
Never hardcode the IRS rate. Look it up by year.

```sql
CREATE TABLE mileage_rates (
  tax_year   INTEGER PRIMARY KEY,
  rate_cents INTEGER NOT NULL,      -- IRS standard business mileage rate, cents per mile
  source     TEXT,                  -- IRS notice reference
  set_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `tax_thresholds`
1099 thresholds change by law/year. Config, not constants.

```sql
CREATE TABLE tax_thresholds (
  tax_year         INTEGER NOT NULL,
  form_type        TEXT NOT NULL,   -- 1099-NEC | 1099-MISC | 1099-K
  threshold_cents  BIGINT NOT NULL,
  txn_count_min    INTEGER,         -- for 1099-K
  notes            TEXT,
  PRIMARY KEY (tax_year, form_type)
);
-- Seed (verify against current IRS guidance before each filing season):
-- (2025,'1099-NEC',60000,NULL,'$600 legacy')
-- (2026,'1099-NEC',200000,NULL,'OBBBA $2,000, payments on/after 2026-01-01')
-- (2026,'1099-MISC',200000,NULL,'OBBBA $2,000')
-- (2026,'1099-K',2000000,200,'$20,000 + 200 txns restored by OBBBA')
```

### `merch_products` / `merch_orders`
```sql
CREATE TABLE merch_products (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sku             TEXT UNIQUE NOT NULL,
  title           TEXT NOT NULL,
  fulfillment     TEXT NOT NULL,     -- pod_printify | pod_printful | local | china
  provider_product_id TEXT,
  base_cost_cents BIGINT,
  retail_cents    BIGINT,
  active          BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE merch_orders (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id        UUID REFERENCES customers(id),
  provider           TEXT,
  provider_order_id  TEXT,
  total_cents        BIGINT NOT NULL,
  cogs_cents         BIGINT,
  status             TEXT NOT NULL DEFAULT 'created',
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `webhook_events`
Dedupe + audit for every inbound provider event.

```sql
CREATE TABLE webhook_events (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider      TEXT NOT NULL,       -- paypal | dwolla | plaid | tax1099
  event_id      TEXT NOT NULL,
  event_type    TEXT NOT NULL,
  payload       JSONB NOT NULL,
  signature_ok  BOOLEAN NOT NULL,
  processed_at  TIMESTAMPTZ,
  received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider, event_id)
);
```

## Acceptance Criteria

- [ ] No column anywhere stores a full bank account or routing number.
- [ ] `SUM(debit) = SUM(credit)` holds for every `entry_id` (constraint trigger present).
- [ ] `mileage_logs` and 1099 logic read rate/threshold from tables, never literals.
- [ ] Every provider webhook insert is rejected on duplicate `(provider, event_id)`.

Read next: [`03-BILLING-PAYPAL.md`](./03-BILLING-PAYPAL.md)
