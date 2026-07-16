# 06 — Ledger Service

The ledger is the foundation. **Build it before payouts.** It is the single source of financial truth; providers are just rails feeding it. Every invoice, payment, payout, fee, refund, expense, and mileage deduction becomes a balanced double-entry transaction.

## Principles

1. **Double-entry.** Every entry has lines that sum: `Σ debits = Σ credits`.
2. **Append-only.** Never `UPDATE` or `DELETE` a money row. Corrections are reversing entries (`reverses_entry`).
3. **Integer cents.** No floats, ever.
4. **Attribution on every line.** PM, customer, project, tax category where applicable — this is what makes tax export and per-PM reporting possible.
5. **Only the Ledger Service writes `ledger_entries` / `ledger_lines`.** Other services call `Ledger.post()`.

## Chart of accounts (seed)

| Code | Name | Type |
|---|---|---|
| `cash` | Operating cash | asset |
| `ar` | Accounts receivable | asset |
| `revenue` | Service revenue | revenue |
| `merch_revenue` | Merch revenue | revenue |
| `payout_expense` | Contractor payouts | expense |
| `processor_fees` | PayPal/Dwolla fees | expense |
| `refunds` | Refunds issued | contra-revenue |
| `vehicle_expense` | Mileage / vehicle | expense |
| `cogs` | Merch cost of goods | expense |
| `materials` | Job materials | expense |

## Canonical entries

**Customer invoice paid** (`amount` = captured, `fee` = processor fee)
```
Dr cash            amount - fee
Dr processor_fees  fee
Cr revenue         amount        (attribute customer_id, project_id)
```

**PM payout completed**
```
Dr payout_expense  amount        (attribute pm_user_id, tax_category='contractor')
Cr cash            amount
```

**Refund issued**
```
Dr refunds         amount
Cr cash            amount
```
(linked via `reverses_entry` to the original payment)

**Expense / receipt confirmed**
```
Dr <expense acct>  amount        (attribute project/customer, tax_category)
Cr cash            amount        (or Cr a liability if on credit)
```

**Mileage deduction** (non-cash, memo entry for tax tracking)
```
Dr vehicle_expense miles*rate    (attribute project, tax_category='vehicle')
Cr equity (owner)  miles*rate    (or a mileage-clearing account)
```

## API surface

```python
Ledger.post(
  entry_type: str,
  occurred_at: datetime,
  lines: list[Line],          # each: account_code, direction, amount_cents, + attribution
  source_table: str|None,
  source_id: UUID|None,
  memo: str|None,
  reverses_entry: UUID|None = None,
) -> entry_id

Ledger.balance(account_code, as_of=None) -> int          # cents
Ledger.pm_ytd_paid(pm_user_id, tax_year) -> int          # for 1099 eligibility
Ledger.pnl(start, end) -> dict                           # revenue/expense rollup
Ledger.reconcile(receipt_id|bank_txn_id) -> match
```

## Invariant enforcement

App-level check **and** a DB constraint trigger:

```sql
CREATE OR REPLACE FUNCTION assert_entry_balanced() RETURNS trigger AS $$
DECLARE d BIGINT; c BIGINT;
BEGIN
  SELECT COALESCE(SUM(amount_cents) FILTER (WHERE direction='debit'),0),
         COALESCE(SUM(amount_cents) FILTER (WHERE direction='credit'),0)
    INTO d, c FROM ledger_lines WHERE entry_id = NEW.entry_id;
  IF d <> c THEN
    RAISE EXCEPTION 'Unbalanced entry %: debits=% credits=%', NEW.entry_id, d, c;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
-- Fire on a DEFERRED constraint trigger after all lines for an entry are inserted.
```

## Reservations (for payouts)

Payouts reserve before settling. Model a reservation as a `pending` ledger state, not a posted entry — only post the settled entry on Dwolla `transfer_completed`. This prevents pending payouts from polluting balances and P&L.

## Period close

- Provide a soft **period lock** (`closed_through` date). Entries with `occurred_at` before the lock are rejected unless they are explicit reversing/adjustment entries flagged for the prior period.
- Generate month-end P&L and balance snapshots for fast reporting.

## Acceptance Criteria

- [ ] Every `Ledger.post()` is balanced or rejected by the constraint trigger.
- [ ] No code path issues `UPDATE`/`DELETE` against `ledger_entries`/`ledger_lines`.
- [ ] `Ledger.pm_ytd_paid()` matches the sum of completed payouts for that PM/year.
- [ ] A refund links to its original payment via `reverses_entry`.
- [ ] Reserved-but-unsettled payouts do not appear in `Ledger.balance('cash')`.

Read next: [`07-TAX-1099.md`](./07-TAX-1099.md)
