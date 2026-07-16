"""Payout Service — Dwolla customer + funding source + two-phase transfer."""
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Optional
import requests
from sqlalchemy.orm import Session
from sqlalchemy import select

import config
from db import new_uuid, utcnow
from models import Payout, PmPayoutProfile, WebhookEvent
from services import ledger


@dataclass
class _Token:
    access_token: str
    expires_at: float


class DwollaClient:
    def __init__(self):
        self.base = config.DWOLLA_BASE
        self.key = config.DWOLLA_KEY
        self.secret = config.DWOLLA_SECRET
        self.master_fs = config.DWOLLA_MASTER_FS
        self.dry_run = not config.has_dwolla()
        self._token: Optional[_Token] = None

    def token(self) -> str:
        if self.dry_run:
            return "dry-run-token"
        now = time.time()
        if self._token and self._token.expires_at > now + 30:
            return self._token.access_token
        auth_header = "Basic " + base64.b64encode(f"{self.key}:{self.secret}".encode()).decode()
        r = requests.post(
            f"{self.base}/token",
            headers={"Authorization": auth_header, "Content-Type": "application/x-www-form-urlencoded"},
            data="grant_type=client_credentials",
            timeout=15,
        )
        r.raise_for_status()
        j = r.json()
        self._token = _Token(j["access_token"], now + int(j.get("expires_in", 3000)))
        return self._token.access_token

    def _h(self, idem: Optional[str] = None) -> dict:
        h = {
            "Authorization": f"Bearer {self.token()}",
            "Accept": "application/vnd.dwolla.v1.hal+json",
            "Content-Type": "application/vnd.dwolla.v1.hal+json",
        }
        if idem:
            h["Idempotency-Key"] = idem
        return h

    def create_customer(self, first_name: str, last_name: str, email: str,
                        receive_only: bool = True, business_name: Optional[str] = None) -> str:
        body = {
            "firstName": first_name,
            "lastName": last_name,
            "email": email,
            "type": "receive-only" if receive_only else "unverified",
        }
        if business_name:
            body["businessName"] = business_name
        if self.dry_run:
            return f"{self.base}/customers/DRY-{new_uuid()[:12]}"
        r = requests.post(f"{self.base}/customers", headers=self._h(), json=body, timeout=20)
        r.raise_for_status()
        return r.headers.get("Location", "")

    def create_funding_source(self, customer_url: str, processor_token: str, name: str) -> str:
        body = {"plaidToken": processor_token, "name": name}
        if self.dry_run:
            return f"{customer_url}/funding-sources/DRY-{new_uuid()[:12]}"
        r = requests.post(f"{customer_url}/funding-sources", headers=self._h(), json=body, timeout=20)
        r.raise_for_status()
        return r.headers.get("Location", "")

    def create_transfer(self, source_fs: str, dest_fs: str, amount_cents: int,
                        metadata: dict, idem: str, same_day: bool = False) -> str:
        body = {
            "_links": {
                "source": {"href": source_fs},
                "destination": {"href": dest_fs},
            },
            "amount": {"currency": "USD", "value": f"{amount_cents/100:.2f}"},
            "metadata": metadata,
        }
        if same_day:
            body["clearing"] = {"destination": "same-day"}
        if self.dry_run:
            return f"{self.base}/transfers/DRY-{new_uuid()[:12]}"
        r = requests.post(f"{self.base}/transfers", headers=self._h(idem=idem), json=body, timeout=20)
        r.raise_for_status()
        return r.headers.get("Location", "")

    def verify_webhook(self, signature_header: str, body: bytes) -> bool:
        if self.dry_run:
            return True
        if not config.DWOLLA_WEBHOOK_SECRET:
            return False
        digest = hmac.new(
            config.DWOLLA_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(digest, signature_header or "")


client = DwollaClient()


def onboard_pm(session: Session, profile_id: str, processor_token: str,
               first_name: str, last_name: str, email: str,
               bank_last4: str) -> dict:
    """Create Dwolla customer + funding source from Plaid processor token."""
    profile = session.get(PmPayoutProfile, profile_id)
    if profile is None:
        raise ValueError("profile not found")
    if not profile.provider_customer_id:
        cust = client.create_customer(first_name, last_name, email, receive_only=True)
        profile.provider_customer_id = cust
    fs = client.create_funding_source(profile.provider_customer_id, processor_token,
                                      name=f"PM checking ••{bank_last4}")
    profile.provider_funding_id = fs
    profile.provider_name = "dwolla"
    profile.bank_last4 = bank_last4[-4:]
    profile.status = "verified"
    profile.updated_at = utcnow().isoformat()
    session.flush()
    return {"customer": profile.provider_customer_id, "funding_source": fs}


def initiate_payout(session: Session, profile_id: str, amount_cents: int,
                    approved_by: str, same_day: bool = False) -> Payout:
    """Two-phase: reserve in ledger → call Dwolla → return payout in 'processing' state."""
    profile = session.get(PmPayoutProfile, profile_id)
    if profile is None:
        raise ValueError("profile not found")
    if profile.status not in ("verified", "active"):
        raise ValueError(f"profile not eligible for payout (status={profile.status})")
    if not profile.provider_funding_id:
        raise ValueError("no funding source")
    if not client.master_fs and not client.dry_run:
        raise ValueError("DWOLLA_MASTER_FUNDING_SOURCE not configured")

    idem = new_uuid()
    p = Payout(
        id=new_uuid(),
        profile_id=profile.id,
        pm_user_id=profile.pm_user_id,
        amount_cents=amount_cents,
        provider="dwolla",
        idempotency_key=idem,
        status="pending",
        approved_by=approved_by,
        approved_at=utcnow().isoformat(),
        created_at=utcnow().isoformat(),
    )
    session.add(p)
    session.flush()

    # Phase 1 — reserve
    res_entry = ledger.reserve_payout(session, p.id, amount_cents, profile.pm_user_id)
    p.reserved_entry_id = res_entry

    # Phase 2 — call Dwolla
    try:
        transfer_url = client.create_transfer(
            source_fs=client.master_fs or "dry-run-master",
            dest_fs=profile.provider_funding_id,
            amount_cents=amount_cents,
            metadata={"payout_id": p.id, "pm_user_id": profile.pm_user_id},
            idem=idem,
            same_day=same_day,
        )
        p.provider_transfer_id = transfer_url
        p.status = "processing"
        p.initiated_at = utcnow().isoformat()
        session.flush()
    except Exception as e:
        ledger.reverse_reservation(session, res_entry, f"dwolla_call_failed:{e}")
        p.status = "failed"
        p.failure_code = "DWOLLA_API_ERROR"
        session.flush()
        raise
    return p


def process_webhook(session: Session, headers: dict, body: bytes) -> dict:
    """Verify HMAC, dedupe, settle / reverse based on event."""
    sig = headers.get("x-request-signature-sha-256", "")
    signature_ok = client.verify_webhook(sig, body)

    body_json = json.loads(body.decode("utf-8") or "{}")
    event_id = body_json.get("id") or new_uuid()
    event_type = body_json.get("topic", "")

    existing = session.execute(
        select(WebhookEvent).where(WebhookEvent.provider == "dwolla",
                                   WebhookEvent.event_id == event_id)
    ).scalar_one_or_none()
    if existing is not None:
        return {"ok": True, "duplicate": True}

    ev = WebhookEvent(
        id=new_uuid(), provider="dwolla", event_id=event_id,
        event_type=event_type, payload=body_json, signature_ok=signature_ok,
        received_at=utcnow().isoformat(),
    )
    session.add(ev)
    session.flush()
    if not signature_ok:
        return {"ok": False, "error": "signature failed"}

    # Find payout by transfer URL in event
    transfer_url = body_json.get("_links", {}).get("resource", {}).get("href", "")
    payout = None
    if transfer_url:
        payout = session.execute(
            select(Payout).where(Payout.provider_transfer_id == transfer_url)
        ).scalar_one_or_none()
    if payout is None:
        # Try metadata
        metadata = body_json.get("metadata") or {}
        if metadata.get("payout_id"):
            payout = session.get(Payout, metadata["payout_id"])

    if payout is not None:
        if event_type == "transfer_completed":
            payout.status = "completed"
            payout.completed_at = utcnow().isoformat()
            if payout.reserved_entry_id:
                ledger.settle_reservation(session, payout.reserved_entry_id)
        elif event_type == "transfer_failed":
            return_code = (body_json.get("resource", {}).get("returnCode") or
                           body_json.get("returnCode") or "R??")
            payout.status = "failed"
            payout.failure_code = return_code
            if payout.reserved_entry_id:
                ledger.reverse_reservation(session, payout.reserved_entry_id, f"failed:{return_code}")
        elif event_type == "transfer_cancelled":
            payout.status = "cancelled"
            if payout.reserved_entry_id:
                ledger.reverse_reservation(session, payout.reserved_entry_id, "cancelled")
        elif event_type == "customer_funding_source_added":
            profile = session.execute(
                select(PmPayoutProfile).where(PmPayoutProfile.id == payout.profile_id)
            ).scalar_one_or_none()
            if profile and profile.status == "pending":
                profile.status = "verified"

    ev.processed_at = utcnow().isoformat()
    session.flush()
    return {"ok": True}
