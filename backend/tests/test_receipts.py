from datetime import datetime, timezone
from db import session_scope, new_uuid
from models import User, Receipt
from services import receipt as receipt_svc, ledger


def test_classify_home_depot():
    code, cat, conf = receipt_svc.classify("Home Depot #6543")
    assert code == "materials"
    assert cat == "materials"
    assert conf >= 0.9


def test_confirm_posts_expense_entry():
    with session_scope() as s:
        u = User(id=new_uuid(), name="PM", role="pm",
                 created_at=datetime.now(timezone.utc).isoformat())
        s.add(u)
        s.flush()
        r = receipt_svc.ingest_upload(s, merchant="Home Depot Plano",
                                      total_cents=4200, pm_user_id=u.id)
        cash_before = ledger.balance(s, "cash")
        confirmed = receipt_svc.confirm(s, r.id)
        assert confirmed.status == "confirmed"
        # Expense decreases cash by amount
        assert ledger.balance(s, "cash") == cash_before - 4200


def test_low_confidence_uncategorized_default():
    code, cat, conf = receipt_svc.classify("Random Mom-n-Pop Shop")
    assert conf <= 0.6
