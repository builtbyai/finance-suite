from datetime import datetime, timezone
from db import session_scope, new_uuid
from models import User, PmPayoutProfile, Payout, TaxThreshold
from services import tax


def test_eligibility_threshold_from_table_2026():
    with session_scope() as s:
        u = User(id=new_uuid(), name="W", role="pm",
                 created_at=datetime.now(timezone.utc).isoformat())
        s.add(u)
        s.flush()
        p = PmPayoutProfile(id=new_uuid(), pm_user_id=u.id, legal_name="L",
                            entity_type="individual",
                            created_at=datetime.now(timezone.utc).isoformat(),
                            updated_at=datetime.now(timezone.utc).isoformat())
        s.add(p)
        s.flush()
        # 2026: threshold is $2,000 = 200000 cents
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        s.add(Payout(id=new_uuid(), profile_id=p.id, pm_user_id=u.id,
                     amount_cents=199999, idempotency_key=new_uuid(),
                     status="completed", completed_at=now.isoformat(),
                     created_at=now.isoformat()))
        s.flush()
        result = tax.compute_1099_eligibility(s, u.id, 2026)
        assert result["threshold_cents"] == 200000
        assert result["eligible"] is False

        # bump over threshold
        s.add(Payout(id=new_uuid(), profile_id=p.id, pm_user_id=u.id,
                     amount_cents=2, idempotency_key=new_uuid(),
                     status="completed", completed_at=now.isoformat(),
                     created_at=now.isoformat()))
        s.flush()
        result2 = tax.compute_1099_eligibility(s, u.id, 2026)
        assert result2["eligible"] is True


def test_w9_stores_only_last4():
    with session_scope() as s:
        u = User(id=new_uuid(), name="X", role="pm",
                 created_at=datetime.now(timezone.utc).isoformat())
        s.add(u)
        s.flush()
        p = PmPayoutProfile(id=new_uuid(), pm_user_id=u.id, legal_name="L",
                            entity_type="individual",
                            created_at=datetime.now(timezone.utc).isoformat(),
                            updated_at=datetime.now(timezone.utc).isoformat())
        s.add(p)
        s.flush()
        rec = tax.collect_w9(s, p.id, tin_last4="123456789")
        assert rec.tin_last4 == "6789"
        assert p.w9_status == "collected"


def test_schedule_c_export_has_categories():
    with session_scope() as s:
        packet = tax.export_schedule_c(s, 2026)
        assert "expense_by_category" in packet
        assert "contractors" in packet
        assert "mileage" in packet
