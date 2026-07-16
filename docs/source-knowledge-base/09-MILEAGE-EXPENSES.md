# 09 — Mileage & Expenses

Mileage is a **first-class ledger input**, not a note. Every logged trip ties to a customer/project/lead and a tax year, populates the customer profile, and produces a deductible vehicle-expense line for the tax packet.

## Why a rate table (never a constant)

The IRS standard business mileage rate changes annually. Hardcoding it breaks historical records the moment the rate updates. Store rates by year (`mileage_rates`) and **snapshot the rate onto each log row at creation** so old logs keep their correct deduction even after the rate changes.

```
deduction_cents = round(miles * rate_cents_for(tax_year))
```

Seed `mileage_rates` with the current IRS rate at the start of each tax year (verify against the IRS notice — the rate is updated yearly and the value is not safe to assume from training data).

## Logging inputs

Captured per trip (see `mileage_logs` schema in `02-DATA-MODEL.md`):

driver · vehicle · start/end location · miles · minutes · purpose · customer · project · lead · reimbursement status · tax year · rate snapshot · computed deduction.

### Capture methods
- **Manual entry** — quick form in Acme Finance.
- **Start/stop GPS** — mobile capture of start/end coords → miles via routing distance.
- **Bulk import** — CSV from a mileage tracker, mapped to logs.

## Ledger treatment

Mileage is a non-cash deduction. Post a memo entry so it flows into the tax packet without affecting cash:

```
Dr vehicle_expense  deduction_cents   (tax_category='vehicle', attribute project/customer)
Cr mileage_clearing deduction_cents
```

Reimbursable mileage (PM driving reimbursed in a payout) is handled differently: the reimbursement is part of the payout amount and posts as cash on payout; the deduction tracking still records the mileage for tax purposes.

## Profile + tax surfaces

- **Customer/project profile:** total miles and trips attributed to that job (useful for job costing and proving on-site visits for claims work).
- **Tax packet:** total business miles × applicable rate per year → Schedule C vehicle line.
- **PM view:** per-PM mileage for reimbursement reconciliation.

## Receipts vs. mileage

Receipts (fuel, materials, tools) flow through `08-RECEIPTS-INGESTION.md`. Mileage uses the standard-rate method here. **Do not double-deduct** — if a PM claims the standard mileage rate, fuel/maintenance receipts for that vehicle are not separately deducted (standard rate already accounts for them). Flag this conflict at categorization time.

## Acceptance Criteria

- [ ] Mileage rate is read from `mileage_rates` and snapshotted onto each log; changing a year's rate never alters past logs.
- [ ] Each log attributes to customer/project and a tax year.
- [ ] Mileage memo entries appear in the tax packet but not in cash balance.
- [ ] Standard-mileage logs and per-vehicle fuel receipts are flagged for double-deduction conflict.

Read next: [`10-MERCH-FULFILLMENT.md`](./10-MERCH-FULFILLMENT.md)
