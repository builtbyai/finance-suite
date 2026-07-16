"""Mileage Service — first-class ledger input, rate snapshotted on log."""
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import select

from db import new_uuid, utcnow
from models import MileageLog, MileageRate
from services import ledger


def rate_for(session: Session, tax_year: int) -> int:
    rate = session.get(MileageRate, tax_year)
    if rate is None:
        raise ValueError(f"no mileage rate seeded for {tax_year} — set tax_thresholds + mileage_rates first")
    return rate.rate_cents


def log_trip(session: Session, *, driver_user_id: str, miles: float, tax_year: int,
             vehicle: Optional[str] = None,
             start_location: Optional[str] = None,
             end_location: Optional[str] = None,
             minutes: Optional[int] = None,
             purpose: Optional[str] = None,
             customer_id: Optional[str] = None,
             project_id: Optional[str] = None,
             lead_id: Optional[str] = None) -> MileageLog:
    rate_cents = rate_for(session, tax_year)
    deduction = int(round(miles * rate_cents))

    log = MileageLog(
        id=new_uuid(),
        driver_user_id=driver_user_id,
        vehicle=vehicle,
        start_location=start_location,
        end_location=end_location,
        miles=miles,
        minutes=minutes,
        purpose=purpose,
        customer_id=customer_id,
        project_id=project_id,
        lead_id=lead_id,
        reimbursement_status="unreimbursed",
        tax_year=tax_year,
        rate_cents=rate_cents,
        deduction_cents=deduction,
        logged_at=utcnow().isoformat(),
    )
    session.add(log)
    session.flush()

    entry_id = ledger.post_mileage(
        session,
        log_id=log.id,
        deduction_cents=deduction,
        pm_user_id=driver_user_id,
        project_id=project_id,
        customer_id=customer_id,
    )
    log.ledger_entry_id = entry_id
    session.flush()
    return log
