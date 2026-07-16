"""Receipt Service — ingestion, classification, confirmation.

Email ingestion (Cloudflare Email Worker + R2) is described in
docs/source-knowledge-base/08-RECEIPTS-INGESTION.md.
This Flask layer handles upload + classify + confirm.
"""
from datetime import datetime
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import select

from db import new_uuid, utcnow
from models import Receipt, BankTransaction
from services import ledger


SCHEDULE_C_CATEGORIES = {
    "Home Depot": ("materials", "materials"),
    "Lowes": ("materials", "materials"),
    "Sherwin-Williams": ("materials", "materials"),
    "Shell": ("vehicle_expense", "vehicle"),
    "Exxon": ("vehicle_expense", "vehicle"),
    "Chevron": ("vehicle_expense", "vehicle"),
    "USPS": ("materials", "office"),
    "FedEx": ("materials", "office"),
}


def classify(merchant: Optional[str]) -> tuple[str, str, float]:
    """Returns (account_code, tax_category, confidence). Deterministic stub for local;
    replace with LLM classifier per 08-RECEIPTS-INGESTION.md in production."""
    if not merchant:
        return ("materials", "uncategorized", 0.30)
    for needle, (code, cat) in SCHEDULE_C_CATEGORIES.items():
        if needle.lower() in merchant.lower():
            return (code, cat, 0.94)
    return ("materials", "materials", 0.55)


def ingest_upload(session: Session, *, source: str = "upload",
                  merchant: Optional[str] = None,
                  total_cents: int = 0,
                  tax_cents: Optional[int] = None,
                  txn_date: Optional[str] = None,
                  r2_key: Optional[str] = None,
                  pm_user_id: Optional[str] = None,
                  project_id: Optional[str] = None,
                  customer_id: Optional[str] = None) -> Receipt:
    code, cat, confidence = classify(merchant)
    r = Receipt(
        id=new_uuid(),
        source=source,
        r2_key=r2_key,
        merchant=merchant,
        total_cents=total_cents,
        tax_cents=tax_cents,
        txn_date=txn_date,
        category=cat,
        confidence=confidence,
        pm_user_id=pm_user_id,
        customer_id=customer_id,
        project_id=project_id,
        status="draft",
        created_at=utcnow().isoformat(),
    )
    session.add(r)
    session.flush()
    return r


def confirm(session: Session, receipt_id: str, override_account_code: Optional[str] = None) -> Receipt:
    r = session.get(Receipt, receipt_id)
    if r is None:
        raise ValueError("receipt not found")
    if r.status == "confirmed":
        return r
    if r.status == "rejected":
        raise ValueError("cannot confirm rejected receipt")
    account_code = override_account_code or classify(r.merchant)[0]
    entry = ledger.post_expense(
        session,
        receipt_id=r.id,
        account_code=account_code,
        amount_cents=r.total_cents or 0,
        tax_category=r.category,
        pm_user_id=r.pm_user_id,
        customer_id=r.customer_id,
        project_id=r.project_id,
    )
    r.status = "confirmed"
    r.ledger_entry_id = entry
    session.flush()
    return r


def reject(session: Session, receipt_id: str) -> Receipt:
    r = session.get(Receipt, receipt_id)
    if r is None:
        raise ValueError("receipt not found")
    r.status = "rejected"
    session.flush()
    return r


def reconcile_bank_feed(session: Session) -> dict:
    """Match bank_transactions ↔ receipts on amount + same posted date."""
    matched = 0
    txns = session.execute(
        select(BankTransaction).where(BankTransaction.matched_receipt_id.is_(None))
    ).scalars().all()
    for t in txns:
        cand = session.execute(
            select(Receipt).where(Receipt.total_cents == t.amount_cents).limit(5)
        ).scalars().all()
        for r in cand:
            if r.status in ("draft", "confirmed") and r.txn_date and t.posted_date and r.txn_date == t.posted_date:
                t.matched_receipt_id = r.id
                t.missing_receipt = False
                if r.status == "confirmed":
                    r.status = "reconciled"
                matched += 1
                break
    session.flush()
    return {"matched": matched}
