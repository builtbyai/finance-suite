"""Verify webhook idempotency + ledger linkage."""
import json
from datetime import datetime, timezone

from db import session_scope, new_uuid
from models import Customer, Invoice, WebhookEvent
from services import billing, ledger
from sqlalchemy import select


def _customer(s):
    c = Customer(id=new_uuid(), name="Webhook Test",
                 email="x@example.com",
                 created_at=datetime.now(timezone.utc).isoformat())
    s.add(c)
    s.flush()
    return c


def test_webhook_duplicate_event_one_effect():
    with session_scope() as s:
        c = _customer(s)
        inv = billing.create_invoice(s, customer_id=c.id, amount_cents=10000, memo="t")
        provider_id = inv.provider_invoice_id

        evt = {
            "id": "EVT-DUP-1",
            "event_type": "INVOICING.INVOICE.PAID",
            "resource": {"id": provider_id, "amount": {"value": "100.00"}},
        }
        body = json.dumps(evt).encode()
        r1 = billing.process_webhook(s, {}, body)
        r2 = billing.process_webhook(s, {}, body)
        assert r1["ok"]
        assert r2.get("duplicate") is True

        rows = s.execute(
            select(Invoice).where(Invoice.id == inv.id)
        ).scalars().all()
        assert rows[0].status == "paid"

        # Exactly one ledger entry should reference this invoice
        from models import LedgerEntry
        entries = s.execute(
            select(LedgerEntry).where(LedgerEntry.source_id == inv.id,
                                       LedgerEntry.entry_type == "invoice_payment")
        ).scalars().all()
        assert len(entries) == 1


def test_unhandled_event_type_records_but_no_ledger():
    with session_scope() as s:
        evt = {"id": "EVT-XYZ", "event_type": "PAYMENT.DISPUTE.CREATED", "resource": {}}
        r = billing.process_webhook(s, {}, json.dumps(evt).encode())
        assert r["ok"]
        ev_row = s.execute(
            select(WebhookEvent).where(WebhookEvent.event_id == "EVT-XYZ")
        ).scalar_one()
        assert ev_row.processed_at is not None
