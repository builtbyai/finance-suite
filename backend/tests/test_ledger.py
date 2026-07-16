import pytest
from datetime import datetime, timezone

from services import ledger
from services.ledger import Line, UnbalancedEntry, LedgerError
from db import session_scope, new_uuid
from models import User, Customer, Payout, PmPayoutProfile


def _pm(s):
    u = User(id=new_uuid(), name="Test PM", role="pm", created_at=datetime.now(timezone.utc).isoformat())
    s.add(u)
    s.flush()
    return u


def test_unbalanced_entry_rejected():
    with session_scope() as s:
        with pytest.raises(UnbalancedEntry):
            ledger.post(s, "invoice_payment", [
                Line("cash", "debit", 1000),
                Line("revenue", "credit", 800),
            ])


def test_balanced_invoice_payment_posts():
    with session_scope() as s:
        eid = ledger.post(s, "invoice_payment", [
            Line("cash", "debit", 970),
            Line("processor_fees", "debit", 30),
            Line("revenue", "credit", 1000),
        ])
        assert eid


def test_post_invoice_payment_helper():
    with session_scope() as s:
        c = Customer(id=new_uuid(), name="T", created_at=datetime.now(timezone.utc).isoformat())
        s.add(c)
        s.flush()
        eid = ledger.post_invoice_payment(s, "inv-1", captured_cents=10000,
                                          processor_fee_cents=300, customer_id=c.id, project_id=None)
        assert eid
        assert ledger.balance(s, "cash") >= 9700


def test_unknown_account_code_raises():
    with session_scope() as s:
        with pytest.raises(LedgerError):
            ledger.post(s, "x", [Line("nonexistent", "debit", 1), Line("cash", "credit", 1)])


def test_reservation_does_not_affect_balance():
    with session_scope() as s:
        pm = _pm(s)
        cash_before = ledger.balance(s, "cash")
        # Reserve 5000 — should NOT change balance
        reservation_eid = ledger.reserve_payout(s, payout_id="p-1",
                                                amount_cents=5000, pm_user_id=pm.id)
        cash_after = ledger.balance(s, "cash")
        assert cash_before == cash_after
        # Settle — NOW the cash balance must drop by 5000
        ledger.settle_reservation(s, reservation_eid)
        assert ledger.balance(s, "cash") == cash_before - 5000


def test_reverse_reservation_keeps_balance_intact():
    with session_scope() as s:
        pm = _pm(s)
        cash_before = ledger.balance(s, "cash")
        eid = ledger.reserve_payout(s, "p-2", 4000, pm.id)
        ledger.reverse_reservation(s, eid, "test_failed")
        assert ledger.balance(s, "cash") == cash_before


def test_pm_ytd_paid_only_counts_completed():
    with session_scope() as s:
        pm = _pm(s)
        prof = PmPayoutProfile(id=new_uuid(), pm_user_id=pm.id, legal_name="x",
                               entity_type="individual",
                               created_at=datetime.now(timezone.utc).isoformat(),
                               updated_at=datetime.now(timezone.utc).isoformat())
        s.add(prof)
        s.flush()

        # Pending payout — should NOT count
        s.add(Payout(id=new_uuid(), profile_id=prof.id, pm_user_id=pm.id,
                     amount_cents=300000, idempotency_key=new_uuid(),
                     status="pending", created_at=datetime.now(timezone.utc).isoformat()))
        # Completed payout this year — should count
        now = datetime.now(timezone.utc)
        s.add(Payout(id=new_uuid(), profile_id=prof.id, pm_user_id=pm.id,
                     amount_cents=250000, idempotency_key=new_uuid(),
                     status="completed", completed_at=now.isoformat(),
                     created_at=now.isoformat()))
        s.flush()
        ytd = ledger.pm_ytd_paid(s, pm.id, now.year)
        assert ytd == 250000


def test_refund_links_via_reverses_entry():
    with session_scope() as s:
        c = Customer(id=new_uuid(), name="T", created_at=datetime.now(timezone.utc).isoformat())
        s.add(c)
        s.flush()
        eid = ledger.post_invoice_payment(s, "inv-x", 5000, 0, c.id, None)
        rid = ledger.post_refund(s, "inv-x", 5000, original_entry_id=eid)
        from models import LedgerEntry
        refund = s.get(LedgerEntry, rid)
        assert refund.reverses_entry == eid


def test_pnl_basic():
    with session_scope() as s:
        c = Customer(id=new_uuid(), name="Pnl test",
                     created_at=datetime.now(timezone.utc).isoformat())
        s.add(c)
        s.flush()
        ledger.post_invoice_payment(s, "inv-pnl", 200000, 6100, c.id, None)
        now = datetime.now(timezone.utc)
        start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
        end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        result = ledger.pnl(s, start, end)
        assert result["revenue_cents"] >= 200000
        assert result["expense_cents"] >= 6100
