"""Ledger Service — double-entry, append-only, integer cents.

The ONLY writer of ledger_entries / ledger_lines.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from db import new_uuid, utcnow
from models import LedgerAccount, LedgerEntry, LedgerLine, Payout


@dataclass
class Line:
    account_code: str
    direction: str  # 'debit' | 'credit'
    amount_cents: int
    pm_user_id: Optional[str] = None
    customer_id: Optional[str] = None
    project_id: Optional[str] = None
    tax_category: Optional[str] = None


class LedgerError(Exception):
    pass


class UnbalancedEntry(LedgerError):
    pass


def _account_id(session: Session, code: str) -> str:
    acct = session.execute(select(LedgerAccount).where(LedgerAccount.code == code)).scalar_one_or_none()
    if not acct:
        raise LedgerError(f"unknown account code: {code}")
    return acct.id


def post(
    session: Session,
    entry_type: str,
    lines: list[Line],
    occurred_at: Optional[datetime] = None,
    source_table: Optional[str] = None,
    source_id: Optional[str] = None,
    memo: Optional[str] = None,
    reverses_entry: Optional[str] = None,
    posted: bool = True,
) -> str:
    """Post a balanced journal entry. Returns entry_id. Raises UnbalancedEntry if Σdebit != Σcredit."""
    if not lines:
        raise LedgerError("entry requires at least one line")

    for ln in lines:
        if ln.amount_cents <= 0:
            raise LedgerError(f"line amount must be > 0, got {ln.amount_cents}")
        if ln.direction not in ("debit", "credit"):
            raise LedgerError(f"invalid direction: {ln.direction}")

    debits = sum(l.amount_cents for l in lines if l.direction == "debit")
    credits = sum(l.amount_cents for l in lines if l.direction == "credit")
    if debits != credits:
        raise UnbalancedEntry(f"unbalanced: debits={debits} credits={credits}")

    entry = LedgerEntry(
        id=new_uuid(),
        entry_type=entry_type,
        source_table=source_table,
        source_id=source_id,
        memo=memo,
        occurred_at=(occurred_at or utcnow()).isoformat(),
        reverses_entry=reverses_entry,
        posted=posted,
    )
    session.add(entry)
    session.flush()

    for ln in lines:
        session.add(LedgerLine(
            id=new_uuid(),
            entry_id=entry.id,
            account_id=_account_id(session, ln.account_code),
            direction=ln.direction,
            amount_cents=ln.amount_cents,
            pm_user_id=ln.pm_user_id,
            customer_id=ln.customer_id,
            project_id=ln.project_id,
            tax_category=ln.tax_category,
        ))

    session.flush()
    return entry.id


def balance(session: Session, account_code: str, as_of: Optional[datetime] = None) -> int:
    """Net balance for an account, in cents. Excludes unposted (reservation) entries."""
    acct_id = _account_id(session, account_code)
    q = (
        select(
            func.coalesce(func.sum(
                LedgerLine.amount_cents *
                # SQLite-safe sign: debit=+1, credit=-1 for asset/expense; opposite for liab/equity/revenue
                # We return raw debit_total - credit_total here; callers may flip per account type.
                # CASE expression
                _direction_sign(),
            ), 0)
        )
        .select_from(LedgerLine)
        .join(LedgerEntry, LedgerEntry.id == LedgerLine.entry_id)
        .where(LedgerLine.account_id == acct_id)
        .where(LedgerEntry.posted == True)  # noqa: E712
    )
    if as_of is not None:
        q = q.where(LedgerEntry.occurred_at <= as_of.isoformat())

    debit_credit = session.execute(q).scalar_one() or 0
    return int(debit_credit)


def _direction_sign():
    from sqlalchemy import case
    return case((LedgerLine.direction == "debit", 1), else_=-1)


def pm_ytd_paid(session: Session, pm_user_id: str, tax_year: int) -> int:
    """Sum of completed payouts for PM in a tax year (cents)."""
    from datetime import datetime
    start = datetime(tax_year, 1, 1, tzinfo=timezone.utc).isoformat()
    end = datetime(tax_year + 1, 1, 1, tzinfo=timezone.utc).isoformat()
    total = session.execute(
        select(func.coalesce(func.sum(Payout.amount_cents), 0))
        .where(Payout.pm_user_id == pm_user_id)
        .where(Payout.status == "completed")
        .where(Payout.completed_at >= start)
        .where(Payout.completed_at < end)
    ).scalar_one()
    return int(total or 0)


def pnl(session: Session, start: datetime, end: datetime) -> dict:
    """Returns {revenue_cents, expense_cents, net_cents} for [start, end)."""
    rev_codes = ("revenue", "merch_revenue")
    exp_codes = ("payout_expense", "processor_fees", "vehicle_expense", "cogs", "materials", "refunds")

    rev = sum(_account_window_sum(session, c, start, end) for c in rev_codes)
    # revenue accounts: credit increases revenue; sum of credit - debit = revenue total
    rev = -rev  # invert since our _direction_sign treats debit as +
    exp = sum(_account_window_sum(session, c, start, end) for c in exp_codes)
    return {
        "revenue_cents": rev,
        "expense_cents": exp,
        "net_cents": rev - exp,
    }


def _account_window_sum(session: Session, code: str, start: datetime, end: datetime) -> int:
    try:
        acct_id = _account_id(session, code)
    except LedgerError:
        return 0
    val = session.execute(
        select(func.coalesce(func.sum(LedgerLine.amount_cents * _direction_sign()), 0))
        .join(LedgerEntry, LedgerEntry.id == LedgerLine.entry_id)
        .where(LedgerLine.account_id == acct_id)
        .where(LedgerEntry.posted == True)  # noqa
        .where(LedgerEntry.occurred_at >= start.isoformat())
        .where(LedgerEntry.occurred_at < end.isoformat())
    ).scalar_one()
    return int(val or 0)


# ----- Reservation API (for payouts) -----

def reserve_payout(session: Session, payout_id: str, amount_cents: int, pm_user_id: str) -> str:
    """Create an UNPOSTED reservation entry. Not visible in balance() until settled."""
    eid = post(
        session,
        entry_type="payout_reservation",
        lines=[
            Line("payout_expense", "debit", amount_cents, pm_user_id=pm_user_id, tax_category="contractor"),
            Line("cash", "credit", amount_cents),
        ],
        source_table="payouts",
        source_id=payout_id,
        memo=f"reservation for payout {payout_id}",
        posted=False,
    )
    return eid


def settle_reservation(session: Session, entry_id: str) -> None:
    """Convert an unposted reservation into a posted entry on Dwolla transfer_completed."""
    entry = session.get(LedgerEntry, entry_id)
    if entry is None:
        raise LedgerError(f"reservation {entry_id} not found")
    if entry.posted:
        return  # idempotent
    entry.posted = True
    entry.entry_type = "payout"
    session.flush()


def reverse_reservation(session: Session, entry_id: str, reason: str) -> None:
    """Drop a reservation that never settled (transfer_failed/cancelled)."""
    entry = session.get(LedgerEntry, entry_id)
    if entry is None:
        return
    if entry.posted:
        raise LedgerError(f"cannot reverse a posted entry via reverse_reservation: {entry_id}")
    # Reservation entries are non-balance-affecting since posted=False, so we just
    # mark the entry_type for audit. We DO NOT delete (append-only).
    entry.entry_type = f"payout_reservation_reversed:{reason}"
    session.flush()


def post_invoice_payment(
    session: Session,
    invoice_id: str,
    captured_cents: int,
    processor_fee_cents: int,
    customer_id: str,
    project_id: Optional[str],
    occurred_at: Optional[datetime] = None,
) -> str:
    """Standard 'customer paid invoice' journal entry."""
    net_cash = captured_cents - processor_fee_cents
    lines = [
        Line("cash", "debit", net_cash),
        Line("revenue", "credit", captured_cents, customer_id=customer_id, project_id=project_id),
    ]
    if processor_fee_cents > 0:
        lines.append(Line("processor_fees", "debit", processor_fee_cents))
    return post(
        session,
        entry_type="invoice_payment",
        lines=lines,
        source_table="invoices",
        source_id=invoice_id,
        occurred_at=occurred_at,
        memo=f"invoice {invoice_id} paid",
    )


def post_refund(
    session: Session,
    invoice_id: str,
    amount_cents: int,
    original_entry_id: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
) -> str:
    return post(
        session,
        entry_type="refund",
        lines=[
            Line("refunds", "debit", amount_cents),
            Line("cash", "credit", amount_cents),
        ],
        source_table="invoices",
        source_id=invoice_id,
        reverses_entry=original_entry_id,
        occurred_at=occurred_at,
        memo=f"refund for invoice {invoice_id}",
    )


def post_expense(
    session: Session,
    receipt_id: str,
    account_code: str,
    amount_cents: int,
    tax_category: Optional[str],
    pm_user_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    project_id: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
) -> str:
    return post(
        session,
        entry_type="expense",
        lines=[
            Line(account_code, "debit", amount_cents,
                 pm_user_id=pm_user_id, customer_id=customer_id, project_id=project_id, tax_category=tax_category),
            Line("cash", "credit", amount_cents),
        ],
        source_table="receipts",
        source_id=receipt_id,
        occurred_at=occurred_at,
    )


def post_mileage(
    session: Session,
    log_id: str,
    deduction_cents: int,
    pm_user_id: str,
    project_id: Optional[str],
    customer_id: Optional[str],
    occurred_at: Optional[datetime] = None,
) -> str:
    """Mileage is a non-cash memo entry: Dr vehicle_expense / Cr mileage_clearing."""
    return post(
        session,
        entry_type="mileage",
        lines=[
            Line("vehicle_expense", "debit", deduction_cents,
                 pm_user_id=pm_user_id, project_id=project_id, customer_id=customer_id,
                 tax_category="vehicle"),
            Line("mileage_clearing", "credit", deduction_cents),
        ],
        source_table="mileage_logs",
        source_id=log_id,
        occurred_at=occurred_at,
    )


def post_merch_sale(
    session: Session,
    order_id: str,
    retail_cents: int,
    cogs_cents: int,
    processor_fee_cents: int,
    customer_id: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
) -> str:
    """Merch order: revenue + COGS in the same entry."""
    lines = [
        Line("cash", "debit", retail_cents - processor_fee_cents),
        Line("merch_revenue", "credit", retail_cents, customer_id=customer_id),
        Line("cogs", "debit", cogs_cents),
        Line("cash", "credit", cogs_cents),
    ]
    if processor_fee_cents > 0:
        lines.append(Line("processor_fees", "debit", processor_fee_cents))
    return post(
        session,
        entry_type="merch_sale",
        lines=lines,
        source_table="merch_orders",
        source_id=order_id,
        occurred_at=occurred_at,
    )
