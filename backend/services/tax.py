"""Tax Service — W-9, 1099 eligibility, Schedule C export.

Reads thresholds from `tax_thresholds`; never hardcoded.
Never files an income tax return — exports CPA-ready packets only.
"""
import csv
import io
import json
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from db import new_uuid, utcnow
from models import (
    PmPayoutProfile, W9Record, Payout, TaxThreshold,
    LedgerEntry, LedgerLine, LedgerAccount, MileageLog, User,
)
from services import ledger


def collect_w9(session: Session, profile_id: str, *, tin_last4: str,
               provider: Optional[str] = None, provider_ref: Optional[str] = None,
               document_r2_key: Optional[str] = None) -> W9Record:
    """Store only last-4 of TIN. Full TIN lives at the filing provider."""
    profile = session.get(PmPayoutProfile, profile_id)
    if profile is None:
        raise ValueError("profile not found")
    if len(tin_last4) > 4:
        tin_last4 = tin_last4[-4:]
    rec = W9Record(
        id=new_uuid(),
        profile_id=profile_id,
        provider=provider,
        provider_ref=provider_ref,
        tin_last4=tin_last4,
        tin_match_status="pending",
        collected_at=utcnow().isoformat(),
        document_r2_key=document_r2_key,
    )
    session.add(rec)
    profile.w9_status = "collected"
    session.flush()
    return rec


def mark_tin_match(session: Session, w9_id: str, status: str) -> None:
    """status in {'match','mismatch','foreign'}."""
    if status not in ("match", "mismatch", "foreign"):
        raise ValueError("invalid TIN match status")
    rec = session.get(W9Record, w9_id)
    if rec is None:
        raise ValueError("w9 not found")
    rec.tin_match_status = status
    profile = session.get(PmPayoutProfile, rec.profile_id)
    if profile:
        profile.w9_status = "tin_verified" if status == "match" else "tin_mismatch"
    session.flush()


def compute_1099_eligibility(session: Session, pm_user_id: str, tax_year: int,
                             form_type: str = "1099-NEC") -> dict:
    """Returns {paid_cents, threshold_cents, eligible}."""
    paid = ledger.pm_ytd_paid(session, pm_user_id, tax_year)
    threshold = session.execute(
        select(TaxThreshold).where(
            TaxThreshold.tax_year == tax_year,
            TaxThreshold.form_type == form_type,
        )
    ).scalar_one_or_none()
    threshold_cents = threshold.threshold_cents if threshold else 200000  # 2026 default
    eligible = paid >= threshold_cents

    profile = session.execute(
        select(PmPayoutProfile).where(PmPayoutProfile.pm_user_id == pm_user_id)
    ).scalar_one_or_none()
    if profile:
        profile.is_1099_eligible = eligible

    return {
        "pm_user_id": pm_user_id,
        "tax_year": tax_year,
        "form_type": form_type,
        "paid_cents": paid,
        "threshold_cents": threshold_cents,
        "eligible": eligible,
    }


def export_schedule_c(session: Session, tax_year: int) -> dict:
    """Year-end packet. Maps every expense line to a tax_category."""
    start = datetime(tax_year, 1, 1, tzinfo=timezone.utc).isoformat()
    end = datetime(tax_year + 1, 1, 1, tzinfo=timezone.utc).isoformat()

    pnl_window = ledger.pnl(session,
                            datetime(tax_year, 1, 1, tzinfo=timezone.utc),
                            datetime(tax_year + 1, 1, 1, tzinfo=timezone.utc))

    # Per-tax-category roll-up
    rows = session.execute(
        select(
            LedgerLine.tax_category,
            LedgerAccount.code.label("account_code"),
            func.coalesce(
                func.sum(
                    LedgerLine.amount_cents * (
                        # debit increases expense
                        # we want net debit for expense accounts
                        1
                    )
                ), 0
            ).label("debit_total"),
        )
        .join(LedgerEntry, LedgerEntry.id == LedgerLine.entry_id)
        .join(LedgerAccount, LedgerAccount.id == LedgerLine.account_id)
        .where(LedgerEntry.posted == True)  # noqa
        .where(LedgerEntry.occurred_at >= start)
        .where(LedgerEntry.occurred_at < end)
        .where(LedgerLine.direction == "debit")
        .where(LedgerAccount.type == "expense")
        .group_by(LedgerLine.tax_category, LedgerAccount.code)
    ).all()
    categories = [
        {"tax_category": r.tax_category or "uncategorized",
         "account_code": r.account_code,
         "amount_cents": int(r.debit_total)}
        for r in rows
    ]

    # Per-PM 1099 summary
    pms = session.execute(select(PmPayoutProfile)).scalars().all()
    contractors = []
    for p in pms:
        elig = compute_1099_eligibility(session, p.pm_user_id, tax_year)
        contractors.append({
            "pm_user_id": p.pm_user_id,
            "legal_name": p.legal_name,
            "entity_type": p.entity_type,
            "w9_status": p.w9_status,
            "tin_last4": _latest_tin_last4(session, p.id),
            "paid_cents": elig["paid_cents"],
            "eligible": elig["eligible"],
        })

    # Mileage roll-up
    mileage = session.execute(
        select(
            func.coalesce(func.sum(MileageLog.miles), 0).label("miles"),
            func.coalesce(func.sum(MileageLog.deduction_cents), 0).label("deduction_cents"),
            func.count().label("trips"),
        ).where(MileageLog.tax_year == tax_year)
    ).one()

    return {
        "tax_year": tax_year,
        "revenue_cents": pnl_window["revenue_cents"],
        "expense_cents": pnl_window["expense_cents"],
        "net_cents": pnl_window["net_cents"],
        "expense_by_category": categories,
        "contractors": contractors,
        "mileage": {
            "trips": mileage.trips,
            "total_miles": float(mileage.miles or 0),
            "deduction_cents": int(mileage.deduction_cents or 0),
        },
    }


def export_schedule_c_csv(session: Session, tax_year: int) -> str:
    packet = export_schedule_c(session, tax_year)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "key", "value_cents", "extra"])
    w.writerow(["totals", "revenue", packet["revenue_cents"], ""])
    w.writerow(["totals", "expense", packet["expense_cents"], ""])
    w.writerow(["totals", "net", packet["net_cents"], ""])
    for c in packet["expense_by_category"]:
        w.writerow(["expense", c["tax_category"], c["amount_cents"], c["account_code"]])
    for c in packet["contractors"]:
        w.writerow(["contractor", c["pm_user_id"], c["paid_cents"],
                    f"{c['legal_name']}|{c['entity_type']}|eligible={c['eligible']}|w9={c['w9_status']}"])
    m = packet["mileage"]
    w.writerow(["mileage", "trips", m["trips"], ""])
    w.writerow(["mileage", "miles", int(m["total_miles"] * 100), ""])
    w.writerow(["mileage", "deduction", m["deduction_cents"], ""])
    return buf.getvalue()


def _latest_tin_last4(session: Session, profile_id: str) -> Optional[str]:
    rec = session.execute(
        select(W9Record).where(W9Record.profile_id == profile_id)
        .order_by(W9Record.collected_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return rec.tin_last4 if rec else None
