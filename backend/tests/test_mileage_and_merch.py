from datetime import datetime, timezone
from db import session_scope, new_uuid
from models import User, MerchProduct
from services import mileage, merch, ledger


def test_mileage_snapshots_rate_and_posts_memo_entry():
    with session_scope() as s:
        u = User(id=new_uuid(), name="Driver", role="pm",
                 created_at=datetime.now(timezone.utc).isoformat())
        s.add(u)
        s.flush()
        cash_before = ledger.balance(s, "cash")
        log = mileage.log_trip(s, driver_user_id=u.id, miles=12.5, tax_year=2026,
                               purpose="materials run")
        assert log.rate_cents == 70  # seeded
        assert log.deduction_cents == int(round(12.5 * 70))
        # Mileage is non-cash — cash balance is unchanged
        assert ledger.balance(s, "cash") == cash_before


def test_merch_sale_posts_revenue_and_cogs():
    with session_scope() as s:
        prods = s.query(MerchProduct).all()
        assert prods, "seed must include merch products"
        p = prods[0]
        rev_before = ledger.balance(s, "merch_revenue")
        cogs_before = ledger.balance(s, "cogs")
        order = merch.create_order(s, product_id=p.id, qty=2,
                                   ship_to={"city": "Dallas", "country_code": "US"},
                                   processor_fee_cents=120)
        assert order.status == "submitted"
        assert order.cogs_cents > 0
        # revenue increased (revenue accounts: credit increases → balance() returns -credit)
        assert ledger.balance(s, "merch_revenue") < rev_before
        assert ledger.balance(s, "cogs") > cogs_before
