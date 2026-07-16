"""Payout two-phase invariant: settled only on transfer_completed."""
import json
from datetime import datetime, timezone

from db import session_scope, new_uuid
from models import User, PmPayoutProfile, Payout
from services import payout as payout_svc, ledger


def _profile(s, *, status="verified"):
    u = User(id=new_uuid(), name="P M", role="pm",
             created_at=datetime.now(timezone.utc).isoformat())
    s.add(u)
    s.flush()
    p = PmPayoutProfile(
        id=new_uuid(), pm_user_id=u.id, legal_name="PM Test",
        entity_type="individual", payout_method="ach_bank",
        provider_name="dwolla",
        provider_customer_id="https://api/customers/test",
        provider_funding_id="https://api/funding-sources/dest",
        bank_last4="1234", status=status,
        w9_status="collected",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    s.add(p)
    s.flush()
    return p, u


def test_initiate_does_not_settle_in_ledger():
    with session_scope() as s:
        p, u = _profile(s)
        cash_before = ledger.balance(s, "cash")
        po = payout_svc.initiate_payout(s, p.id, 25000, approved_by=None)
        assert po.status == "processing"
        # Cash balance must NOT change yet — reservation is unposted
        assert ledger.balance(s, "cash") == cash_before


def test_transfer_completed_settles_ledger_and_ytd():
    with session_scope() as s:
        p, u = _profile(s)
        po = payout_svc.initiate_payout(s, p.id, 50000, approved_by=None)
        cash_before = ledger.balance(s, "cash")

        evt = {
            "id": "DW-COMPLETED-1",
            "topic": "transfer_completed",
            "_links": {"resource": {"href": po.provider_transfer_id}},
        }
        r = payout_svc.process_webhook(s, {}, json.dumps(evt).encode())
        assert r["ok"]

        s.refresh(po)
        assert po.status == "completed"
        # Now cash should drop by the payout
        assert ledger.balance(s, "cash") == cash_before - 50000
        assert ledger.pm_ytd_paid(s, u.id, datetime.now(timezone.utc).year) == 50000


def test_transfer_failed_reverses_and_no_ytd_increment():
    with session_scope() as s:
        p, u = _profile(s)
        po = payout_svc.initiate_payout(s, p.id, 30000, approved_by=None)
        cash_before = ledger.balance(s, "cash")

        evt = {
            "id": "DW-FAILED-1",
            "topic": "transfer_failed",
            "_links": {"resource": {"href": po.provider_transfer_id}},
            "resource": {"returnCode": "R01"},
        }
        r = payout_svc.process_webhook(s, {}, json.dumps(evt).encode())
        assert r["ok"]
        s.refresh(po)
        assert po.status == "failed"
        assert po.failure_code == "R01"
        # No cash impact
        assert ledger.balance(s, "cash") == cash_before
        # No YTD increment
        assert ledger.pm_ytd_paid(s, u.id, datetime.now(timezone.utc).year) == 0


def test_duplicate_webhook_does_not_double_settle():
    with session_scope() as s:
        p, u = _profile(s)
        po = payout_svc.initiate_payout(s, p.id, 70000, approved_by=None)
        evt = {
            "id": "DW-DUP-1",
            "topic": "transfer_completed",
            "_links": {"resource": {"href": po.provider_transfer_id}},
        }
        body = json.dumps(evt).encode()
        payout_svc.process_webhook(s, {}, body)
        cash_after_first = ledger.balance(s, "cash")
        r2 = payout_svc.process_webhook(s, {}, body)
        assert r2.get("duplicate") is True
        assert ledger.balance(s, "cash") == cash_after_first
