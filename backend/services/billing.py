"""Billing Service — PayPal Invoicing API."""
import base64
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Optional
import requests
from sqlalchemy.orm import Session
from sqlalchemy import select

import config
from db import new_uuid, utcnow
from models import Invoice, Customer, WebhookEvent
from services import ledger


@dataclass
class _Token:
    access_token: str
    expires_at: float


class PayPalClient:
    """Thin wrapper. dry_run=True records DB state without HTTP."""

    def __init__(self):
        self.base = config.PAYPAL_BASE
        self.client_id = config.PAYPAL_CLIENT_ID
        self.client_secret = config.PAYPAL_CLIENT_SECRET
        self.dry_run = not config.has_paypal()
        self._token: Optional[_Token] = None

    def token(self) -> str:
        if self.dry_run:
            return "dry-run-token"
        now = time.time()
        if self._token and self._token.expires_at > now + 30:
            return self._token.access_token
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        r = requests.post(
            f"{self.base}/v1/oauth2/token",
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
            data="grant_type=client_credentials",
            timeout=15,
        )
        r.raise_for_status()
        j = r.json()
        self._token = _Token(j["access_token"], now + int(j.get("expires_in", 3000)))
        return self._token.access_token

    def _h(self, idem: Optional[str] = None) -> dict:
        h = {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json"}
        if idem:
            h["PayPal-Request-Id"] = idem
        return h

    def create_invoice(self, *, customer_email: str, number: str, amount_cents: int,
                       memo: Optional[str] = None, reference: Optional[str] = None) -> dict:
        body = {
            "detail": {
                "currency_code": "USD",
                "invoice_number": number,
                "note": memo or "",
                "reference": reference or "",
            },
            "primary_recipients": [{"billing_info": {"email_address": customer_email}}],
            "items": [{
                "name": memo or "Services",
                "quantity": "1",
                "unit_amount": {"currency_code": "USD", "value": f"{amount_cents/100:.2f}"},
            }],
        }
        if self.dry_run:
            return {
                "id": f"INV2-DRY-{new_uuid()[:8]}",
                "status": "DRAFT",
                "links": [],
            }
        r = requests.post(f"{self.base}/v2/invoicing/invoices",
                          headers=self._h(idem=number), json=body, timeout=20)
        r.raise_for_status()
        return r.json()

    def send_invoice(self, provider_invoice_id: str) -> Optional[str]:
        if self.dry_run:
            return f"{self.base}/invoice/p/#{provider_invoice_id}"
        r = requests.post(f"{self.base}/v2/invoicing/invoices/{provider_invoice_id}/send",
                          headers=self._h(), json={"send_to_recipient": True}, timeout=20)
        r.raise_for_status()
        return r.headers.get("Location")

    def get_invoice(self, provider_invoice_id: str) -> dict:
        if self.dry_run:
            return {"id": provider_invoice_id, "status": "SENT"}
        r = requests.get(f"{self.base}/v2/invoicing/invoices/{provider_invoice_id}",
                         headers=self._h(), timeout=15)
        r.raise_for_status()
        return r.json()

    def cancel_invoice(self, provider_invoice_id: str) -> None:
        if self.dry_run:
            return
        requests.post(f"{self.base}/v2/invoicing/invoices/{provider_invoice_id}/cancel",
                      headers=self._h(), json={"send_to_recipient": True}, timeout=15).raise_for_status()

    def refund_invoice(self, provider_invoice_id: str, amount_cents: int) -> dict:
        body = {"amount": {"currency_code": "USD", "value": f"{amount_cents/100:.2f}"}}
        if self.dry_run:
            return {"refund_id": f"REF-DRY-{new_uuid()[:8]}"}
        r = requests.post(f"{self.base}/v2/invoicing/invoices/{provider_invoice_id}/refunds",
                          headers=self._h(), json=body, timeout=20)
        r.raise_for_status()
        return r.json()

    def verify_webhook(self, headers: dict, body_json: dict) -> bool:
        if self.dry_run:
            return True
        if not config.PAYPAL_WEBHOOK_ID:
            return False
        payload = {
            "transmission_id": headers.get("paypal-transmission-id"),
            "transmission_time": headers.get("paypal-transmission-time"),
            "cert_url": headers.get("paypal-cert-url"),
            "auth_algo": headers.get("paypal-auth-algo"),
            "transmission_sig": headers.get("paypal-transmission-sig"),
            "webhook_id": config.PAYPAL_WEBHOOK_ID,
            "webhook_event": body_json,
        }
        r = requests.post(f"{self.base}/v1/notifications/verify-webhook-signature",
                          headers=self._h(), json=payload, timeout=15)
        r.raise_for_status()
        return r.json().get("verification_status") == "SUCCESS"


client = PayPalClient()


# -------- DB helpers --------

def create_invoice(session: Session, *, customer_id: str, amount_cents: int,
                   number: Optional[str] = None, memo: Optional[str] = None,
                   project_id: Optional[str] = None) -> Invoice:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise ValueError("customer_id not found")
    if number is None:
        # naive sequential — production would call /v2/invoicing/generate-next-invoice-number
        from sqlalchemy import func
        count = session.execute(select(func.count()).select_from(Invoice)).scalar_one() or 0
        number = f"INV-{utcnow().year}-{(count + 1):04d}"

    paypal = client.create_invoice(
        customer_email=customer.email or "no-reply@example.com",
        number=number,
        amount_cents=amount_cents,
        memo=memo,
        reference=f"project_id:{project_id}" if project_id else "",
    )

    inv = Invoice(
        id=new_uuid(),
        customer_id=customer_id,
        project_id=project_id,
        provider="paypal",
        provider_invoice_id=paypal.get("id"),
        number=number,
        amount_cents=amount_cents,
        status="draft",
        created_at=utcnow().isoformat(),
    )
    session.add(inv)
    session.flush()
    return inv


def send_invoice(session: Session, invoice_id: str) -> Invoice:
    inv = session.get(Invoice, invoice_id)
    if inv is None:
        raise ValueError("invoice not found")
    payable = client.send_invoice(inv.provider_invoice_id)
    inv.status = "sent"
    inv.issued_at = utcnow().isoformat()
    inv.payable_url = payable
    session.flush()
    return inv


def cancel_invoice(session: Session, invoice_id: str) -> Invoice:
    inv = session.get(Invoice, invoice_id)
    if inv is None:
        raise ValueError("invoice not found")
    client.cancel_invoice(inv.provider_invoice_id)
    inv.status = "cancelled"
    session.flush()
    return inv


def refund_invoice(session: Session, invoice_id: str, amount_cents: int) -> Invoice:
    inv = session.get(Invoice, invoice_id)
    if inv is None:
        raise ValueError("invoice not found")
    client.refund_invoice(inv.provider_invoice_id, amount_cents)
    inv.status = "refunded"
    ledger.post_refund(session, invoice_id, amount_cents)
    session.flush()
    return inv


# -------- Webhook handling --------

def process_webhook(session: Session, headers: dict, body: bytes) -> dict:
    """Dedupe by event_id, verify signature, dispatch to ledger."""
    body_json = json.loads(body.decode("utf-8") or "{}")
    event_id = body_json.get("id")
    event_type = body_json.get("event_type", "")
    if not event_id:
        return {"ok": False, "error": "missing event id"}

    # Dedupe
    existing = session.execute(
        select(WebhookEvent).where(WebhookEvent.provider == "paypal",
                                   WebhookEvent.event_id == event_id)
    ).scalar_one_or_none()
    if existing is not None:
        return {"ok": True, "duplicate": True}

    signature_ok = client.verify_webhook(headers, body_json)

    ev = WebhookEvent(
        id=new_uuid(),
        provider="paypal",
        event_id=event_id,
        event_type=event_type,
        payload=body_json,
        signature_ok=signature_ok,
        received_at=utcnow().isoformat(),
    )
    session.add(ev)
    session.flush()

    if not signature_ok:
        return {"ok": False, "error": "signature failed"}

    if event_type == "INVOICING.INVOICE.PAID":
        _on_invoice_paid(session, body_json)
    elif event_type == "INVOICING.INVOICE.REFUNDED":
        _on_invoice_refunded(session, body_json)
    elif event_type == "INVOICING.INVOICE.CANCELLED":
        _on_invoice_cancelled(session, body_json)

    ev.processed_at = utcnow().isoformat()
    session.flush()
    return {"ok": True}


def _on_invoice_paid(session: Session, ev: dict) -> None:
    resource = ev.get("resource", {})
    pid = resource.get("id") or resource.get("invoice", {}).get("id")
    if not pid:
        return
    inv = session.execute(select(Invoice).where(Invoice.provider_invoice_id == pid)).scalar_one_or_none()
    if inv is None:
        return
    captured = int(round(float(resource.get("amount", {}).get("value", "0") or
                              resource.get("invoice", {}).get("amount", {}).get("value", "0")) * 100))
    if captured == 0:
        captured = inv.amount_cents
    inv.status = "paid"
    inv.paid_at = utcnow().isoformat()
    # Approximate fee: 2.9% + 30¢; in production read from PayPal "transactions" detail
    fee = int(round(captured * 0.029)) + 30
    ledger.post_invoice_payment(
        session,
        invoice_id=inv.id,
        captured_cents=captured,
        processor_fee_cents=fee,
        customer_id=inv.customer_id,
        project_id=inv.project_id,
    )


def _on_invoice_refunded(session: Session, ev: dict) -> None:
    pid = (ev.get("resource", {}).get("id") or
           ev.get("resource", {}).get("invoice", {}).get("id"))
    if not pid:
        return
    inv = session.execute(select(Invoice).where(Invoice.provider_invoice_id == pid)).scalar_one_or_none()
    if inv is None:
        return
    inv.status = "refunded"
    ledger.post_refund(session, inv.id, inv.amount_cents)


def _on_invoice_cancelled(session: Session, ev: dict) -> None:
    pid = (ev.get("resource", {}).get("id") or
           ev.get("resource", {}).get("invoice", {}).get("id"))
    if not pid:
        return
    inv = session.execute(select(Invoice).where(Invoice.provider_invoice_id == pid)).scalar_one_or_none()
    if inv:
        inv.status = "cancelled"


def reconcile_polling(session: Session) -> int:
    """Nightly fallback: re-check `sent` invoices, mark paid via direct GET."""
    rows = session.execute(
        select(Invoice).where(Invoice.status.in_(("sent",))).limit(200)
    ).scalars().all()
    n = 0
    for inv in rows:
        info = client.get_invoice(inv.provider_invoice_id)
        if info.get("status") == "PAID":
            inv.status = "paid"
            inv.paid_at = utcnow().isoformat()
            ledger.post_invoice_payment(
                session, inv.id, inv.amount_cents,
                processor_fee_cents=int(round(inv.amount_cents * 0.029)) + 30,
                customer_id=inv.customer_id, project_id=inv.project_id,
            )
            n += 1
    return n
