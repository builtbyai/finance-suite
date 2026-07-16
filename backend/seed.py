"""Idempotent seeder: chart of accounts, tax thresholds, mileage rates, demo data.

Run: python seed.py
"""
from sqlalchemy import select
from db import Base, engine, session_scope, new_uuid, utcnow
from models import (
    LedgerAccount, TaxThreshold, MileageRate,
    User, Customer, MerchProduct,
)


CHART = [
    ("cash", "Operating cash", "asset"),
    ("ar", "Accounts receivable", "asset"),
    ("revenue", "Service revenue", "revenue"),
    ("merch_revenue", "Merch revenue", "revenue"),
    ("payout_expense", "Contractor payouts", "expense"),
    ("processor_fees", "PayPal/Dwolla fees", "expense"),
    ("refunds", "Refunds issued", "expense"),
    ("vehicle_expense", "Mileage / vehicle", "expense"),
    ("cogs", "Cost of goods sold", "expense"),
    ("materials", "Job materials", "expense"),
    ("mileage_clearing", "Mileage clearing (memo)", "equity"),
]


# OBBBA 2026 thresholds — see docs/source-knowledge-base/07-TAX-1099.md.
# Values in cents.
THRESHOLDS = [
    (2025, "1099-NEC", 60000, None, "$600 legacy"),
    (2025, "1099-MISC", 60000, None, "$600 legacy"),
    (2026, "1099-NEC", 200000, None, "OBBBA $2,000, on/after 2026-01-01"),
    (2026, "1099-MISC", 200000, None, "OBBBA $2,000"),
    (2026, "1099-K", 2000000, 200, "$20,000 + 200 txns restored by OBBBA"),
]


# IRS standard business mileage rate, cents per mile.
# VERIFY before each tax season — these are the placeholders from the spec.
MILEAGE_RATES = [
    (2024, 67, "IRS Notice 2024-08"),
    (2025, 70, "IRS Notice 2025-XX (verify)"),
    (2026, 70, "IRS Notice 2026-XX (verify)"),
]


def run():
    Base.metadata.create_all(engine)
    with session_scope() as s:
        for code, name, type_ in CHART:
            if s.execute(select(LedgerAccount).where(LedgerAccount.code == code)).scalar_one_or_none() is None:
                s.add(LedgerAccount(id=new_uuid(), code=code, name=name, type=type_))

        for year, form, cents, txns, notes in THRESHOLDS:
            existing = s.execute(
                select(TaxThreshold).where(TaxThreshold.tax_year == year,
                                           TaxThreshold.form_type == form)
            ).scalar_one_or_none()
            if existing is None:
                s.add(TaxThreshold(tax_year=year, form_type=form,
                                   threshold_cents=cents, txn_count_min=txns, notes=notes))
            else:
                existing.threshold_cents = cents
                existing.txn_count_min = txns
                existing.notes = notes

        for year, rate, src in MILEAGE_RATES:
            if s.execute(select(MileageRate).where(MileageRate.tax_year == year)).scalar_one_or_none() is None:
                s.add(MileageRate(tax_year=year, rate_cents=rate, source=src, set_at=utcnow().isoformat()))

        # Demo seed (so the UI has something to show)
        if s.execute(select(User)).first() is None:
            admin = User(id=new_uuid(), email="alex@example.com",
                         name="Alex Morgan", role="admin", created_at=utcnow().isoformat())
            pm = User(id=new_uuid(), email="jordan@example.com",
                      name="Jordan Lee", role="pm", created_at=utcnow().isoformat())
            s.add(admin)
            s.add(pm)

        if s.execute(select(Customer)).first() is None:
            s.add(Customer(id=new_uuid(), name="John Smith",
                           email="john.smith@example.com", phone="+15555550100",
                           created_at=utcnow().isoformat()))

        if s.execute(select(MerchProduct)).first() is None:
            s.add(MerchProduct(id=new_uuid(), sku="ACME-TEE-BLK",
                               title="Acme Black Tee", fulfillment="pod_printful",
                               base_cost_cents=1450, retail_cents=3200, active=True))
            s.add(MerchProduct(id=new_uuid(), sku="ACME-CAP-GLD",
                               title="Acme Gold Cap", fulfillment="pod_printify",
                               base_cost_cents=1200, retail_cents=2800, active=True))

    print("seed OK")


if __name__ == "__main__":
    run()
