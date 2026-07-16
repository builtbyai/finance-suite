-- Postgres init for production (db-host). Local dev uses SQLAlchemy create_all on SQLite.
-- Mirrors the schema in docs/source-knowledge-base/02-DATA-MODEL.md.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Users / projects / customers
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT, name TEXT, role TEXT DEFAULT 'pm',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS customers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL, email TEXT, phone TEXT,
  project_id UUID REFERENCES projects(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- PM payout
CREATE TABLE IF NOT EXISTS pm_payout_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pm_user_id UUID NOT NULL REFERENCES users(id),
  legal_name TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  tax_classification TEXT,
  payout_method TEXT NOT NULL,
  provider_name TEXT, provider_customer_id TEXT, provider_funding_id TEXT,
  bank_name TEXT, bank_last4 CHAR(4), account_type TEXT,
  plaid_item_id TEXT, plaid_access_token_enc TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  w9_status TEXT NOT NULL DEFAULT 'not_collected',
  is_1099_eligible BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payout_authorizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID NOT NULL REFERENCES pm_payout_profiles(id),
  consent_version TEXT NOT NULL, consent_text_hash TEXT NOT NULL,
  authorized_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ip_address INET NOT NULL, user_agent TEXT NOT NULL,
  revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS invoices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id UUID NOT NULL REFERENCES customers(id),
  project_id UUID REFERENCES projects(id),
  provider TEXT NOT NULL DEFAULT 'paypal',
  provider_invoice_id TEXT UNIQUE,
  number TEXT NOT NULL,
  amount_cents BIGINT NOT NULL,
  currency CHAR(3) NOT NULL DEFAULT 'USD',
  status TEXT NOT NULL DEFAULT 'draft',
  payable_url TEXT, issued_at TIMESTAMPTZ, paid_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ledger_accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entry_type TEXT NOT NULL,
  source_table TEXT, source_id UUID,
  memo TEXT,
  occurred_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  reverses_entry UUID REFERENCES ledger_entries(id),
  posted BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS ledger_lines (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entry_id UUID NOT NULL REFERENCES ledger_entries(id),
  account_id UUID NOT NULL REFERENCES ledger_accounts(id),
  direction TEXT NOT NULL CHECK (direction IN ('debit','credit')),
  amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
  pm_user_id UUID REFERENCES users(id),
  customer_id UUID REFERENCES customers(id),
  project_id UUID REFERENCES projects(id),
  tax_category TEXT
);
CREATE INDEX IF NOT EXISTS ix_ledger_lines_entry ON ledger_lines(entry_id);

-- Constraint trigger: every entry must balance.
CREATE OR REPLACE FUNCTION assert_entry_balanced() RETURNS trigger AS $$
DECLARE d BIGINT; c BIGINT;
BEGIN
  SELECT COALESCE(SUM(amount_cents) FILTER (WHERE direction='debit'),0),
         COALESCE(SUM(amount_cents) FILTER (WHERE direction='credit'),0)
    INTO d, c
    FROM ledger_lines WHERE entry_id = NEW.entry_id;
  IF d <> c THEN
    RAISE EXCEPTION 'Unbalanced entry %: debits=% credits=%', NEW.entry_id, d, c;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ledger_balanced ON ledger_lines;
CREATE CONSTRAINT TRIGGER trg_ledger_balanced
  AFTER INSERT OR UPDATE ON ledger_lines
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW
  EXECUTE FUNCTION assert_entry_balanced();

CREATE TABLE IF NOT EXISTS payouts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID NOT NULL REFERENCES pm_payout_profiles(id),
  pm_user_id UUID NOT NULL REFERENCES users(id),
  amount_cents BIGINT NOT NULL,
  provider TEXT NOT NULL DEFAULT 'dwolla',
  provider_transfer_id TEXT UNIQUE,
  idempotency_key TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  failure_code TEXT,
  approved_by UUID REFERENCES users(id),
  approved_at TIMESTAMPTZ, initiated_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
  reserved_entry_id UUID REFERENCES ledger_entries(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS w9_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID NOT NULL REFERENCES pm_payout_profiles(id),
  provider TEXT, provider_ref TEXT,
  tin_last4 CHAR(4), tin_match_status TEXT,
  collected_at TIMESTAMPTZ, document_r2_key TEXT
);

CREATE TABLE IF NOT EXISTS receipts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT NOT NULL,
  r2_key TEXT, raw_email_key TEXT,
  merchant TEXT,
  total_cents BIGINT, tax_cents BIGINT,
  txn_date DATE, category TEXT, confidence NUMERIC(4,3),
  pm_user_id UUID REFERENCES users(id),
  customer_id UUID REFERENCES customers(id),
  project_id UUID REFERENCES projects(id),
  status TEXT NOT NULL DEFAULT 'draft',
  ledger_entry_id UUID REFERENCES ledger_entries(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bank_transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plaid_account_id TEXT NOT NULL,
  plaid_txn_id TEXT UNIQUE NOT NULL,
  amount_cents BIGINT NOT NULL,
  name TEXT, category TEXT, posted_date DATE,
  pending BOOLEAN DEFAULT FALSE,
  matched_receipt_id UUID REFERENCES receipts(id),
  missing_receipt BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mileage_rates (
  tax_year INTEGER PRIMARY KEY,
  rate_cents INTEGER NOT NULL,
  source TEXT,
  set_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mileage_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  driver_user_id UUID NOT NULL REFERENCES users(id),
  vehicle TEXT, start_location TEXT, end_location TEXT,
  miles NUMERIC(8,2) NOT NULL, minutes INTEGER, purpose TEXT,
  customer_id UUID REFERENCES customers(id),
  project_id UUID REFERENCES projects(id),
  lead_id UUID,
  reimbursement_status TEXT DEFAULT 'unreimbursed',
  tax_year INTEGER NOT NULL,
  rate_cents INTEGER, deduction_cents BIGINT,
  ledger_entry_id UUID REFERENCES ledger_entries(id),
  logged_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tax_thresholds (
  tax_year INTEGER NOT NULL,
  form_type TEXT NOT NULL,
  threshold_cents BIGINT NOT NULL,
  txn_count_min INTEGER, notes TEXT,
  PRIMARY KEY (tax_year, form_type)
);

CREATE TABLE IF NOT EXISTS merch_products (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sku TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
  fulfillment TEXT NOT NULL, provider_product_id TEXT,
  base_cost_cents BIGINT, retail_cents BIGINT,
  active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS merch_orders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id UUID REFERENCES customers(id),
  product_id UUID NOT NULL REFERENCES merch_products(id),
  qty INTEGER NOT NULL DEFAULT 1,
  provider TEXT, provider_order_id TEXT,
  total_cents BIGINT NOT NULL, cogs_cents BIGINT,
  status TEXT NOT NULL DEFAULT 'created',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS webhook_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider TEXT NOT NULL,
  event_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  signature_ok BOOLEAN NOT NULL,
  processed_at TIMESTAMPTZ,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider, event_id)
);
