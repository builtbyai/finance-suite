-- 0002_customer_external_id_and_audit.sql
-- Adds external_id + address to customers so the Worker's
-- /api/internal/customers/upsert can be idempotent (one row per CRM lead).
-- Adds audit columns to every business table per the v1 sellability gap
-- audit (regulators expect created_by / updated_by on finance data).

BEGIN;

ALTER TABLE customers ADD COLUMN address TEXT;
ALTER TABLE customers ADD COLUMN external_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_customers_external_id
  ON customers (external_id) WHERE external_id IS NOT NULL;

-- Audit columns. user_id strings come from the Worker JWT (X-User-JWT header).
ALTER TABLE customers       ADD COLUMN created_by TEXT;
ALTER TABLE customers       ADD COLUMN updated_by TEXT;
ALTER TABLE invoices        ADD COLUMN created_by TEXT;
ALTER TABLE invoices        ADD COLUMN updated_by TEXT;
ALTER TABLE payouts         ADD COLUMN created_by TEXT;
ALTER TABLE payouts         ADD COLUMN updated_by TEXT;
ALTER TABLE receipts        ADD COLUMN created_by TEXT;
ALTER TABLE receipts        ADD COLUMN updated_by TEXT;
ALTER TABLE mileage_logs    ADD COLUMN created_by TEXT;
ALTER TABLE mileage_logs    ADD COLUMN updated_by TEXT;
ALTER TABLE ledger_entries  ADD COLUMN created_by TEXT;
ALTER TABLE ledger_entries  ADD COLUMN updated_by TEXT;

-- Double-entry invariant enforced at DB layer, not just Python. Any commit
-- whose sum of debits != sum of credits per entry_id is rejected.
CREATE OR REPLACE FUNCTION enforce_balanced_ledger() RETURNS trigger AS $$
DECLARE
  total_debit  NUMERIC;
  total_credit NUMERIC;
BEGIN
  SELECT
    COALESCE(SUM(debit_cents), 0),
    COALESCE(SUM(credit_cents), 0)
  INTO total_debit, total_credit
  FROM ledger_lines
  WHERE entry_id = NEW.entry_id;

  IF total_debit <> total_credit THEN
    RAISE EXCEPTION 'ledger entry % is unbalanced: debit=% credit=%',
      NEW.entry_id, total_debit, total_credit;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_enforce_balanced_ledger ON ledger_lines;
CREATE CONSTRAINT TRIGGER trg_enforce_balanced_ledger
  AFTER INSERT OR UPDATE OR DELETE ON ledger_lines
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION enforce_balanced_ledger();

COMMIT;
