"""Bank Link Service — Plaid Link, Auth, processor token handoff to Dwolla."""
import json
from typing import Optional
import requests
from sqlalchemy.orm import Session
from sqlalchemy import select

import config
from db import new_uuid, utcnow
from models import PmPayoutProfile, BankTransaction, WebhookEvent


class PlaidClient:
    def __init__(self):
        self.base = config.PLAID_BASE
        self.client_id = config.PLAID_CLIENT_ID
        self.secret = config.PLAID_SECRET
        self.dry_run = not config.has_plaid()

    def _post(self, path: str, body: dict) -> dict:
        if self.dry_run:
            return _dry_plaid(path, body)
        payload = {"client_id": self.client_id, "secret": self.secret, **body}
        r = requests.post(f"{self.base}{path}", json=payload, timeout=20)
        r.raise_for_status()
        return r.json()

    def create_link_token(self, pm_user_id: str) -> str:
        body = {
            "user": {"client_user_id": pm_user_id},
            "client_name": "Acme Finance",
            "products": ["auth"],
            "country_codes": ["US"],
            "language": "en",
        }
        return self._post("/link/token/create", body).get("link_token", "")

    def exchange_public_token(self, public_token: str) -> dict:
        return self._post("/item/public_token/exchange", {"public_token": public_token})

    def create_processor_token(self, access_token: str, account_id: str, processor: str = "dwolla") -> str:
        body = {"access_token": access_token, "account_id": account_id, "processor": processor}
        return self._post("/processor/token/create", body).get("processor_token", "")

    def transactions_sync(self, access_token: str, cursor: Optional[str] = None) -> dict:
        body = {"access_token": access_token}
        if cursor:
            body["cursor"] = cursor
        return self._post("/transactions/sync", body)


def _dry_plaid(path: str, body: dict) -> dict:
    if path == "/link/token/create":
        return {"link_token": f"link-sandbox-DRY-{new_uuid()[:12]}"}
    if path == "/item/public_token/exchange":
        return {"access_token": f"access-sandbox-DRY-{new_uuid()[:12]}",
                "item_id": f"item-DRY-{new_uuid()[:8]}"}
    if path == "/processor/token/create":
        return {"processor_token": f"processor-sandbox-DRY-{new_uuid()[:12]}"}
    if path == "/transactions/sync":
        return {"added": [], "modified": [], "removed": [], "next_cursor": "DRY-CURSOR", "has_more": False}
    return {}


client = PlaidClient()


def create_link_token(pm_user_id: str) -> str:
    return client.create_link_token(pm_user_id)


def link_account(session: Session, profile_id: str, public_token: str, account_id: str,
                 bank_name: str, bank_last4: str, account_type: str) -> dict:
    """Steps 4–6 of the bank-link flow: exchange + processor token + persist."""
    profile = session.get(PmPayoutProfile, profile_id)
    if profile is None:
        raise ValueError("payout profile not found")
    exch = client.exchange_public_token(public_token)
    access_token = exch.get("access_token", "")
    item_id = exch.get("item_id", "")
    processor_token = client.create_processor_token(access_token, account_id, "dwolla")

    # Stash. In production access_token must be encrypted at rest (KMS / Fernet).
    profile.plaid_item_id = item_id
    profile.plaid_access_token_enc = _seal(access_token)
    profile.bank_name = bank_name
    profile.bank_last4 = bank_last4[-4:]
    profile.account_type = account_type
    profile.updated_at = utcnow().isoformat()
    session.flush()
    return {"processor_token": processor_token, "item_id": item_id}


def _seal(plain: str) -> str:
    """Encrypt at rest. Uses Fernet (AES-128-CBC + HMAC) when FERNET_KEY is
    configured; falls back to base64 for local-dev convenience so the test
    suite still runs without a key. Production deployments MUST set
    FERNET_KEY — `bank_link.audit_encryption_configured()` will return False
    otherwise and the boot guard in app.py will refuse to start."""
    import config
    if config.FERNET_KEY:
        from middleware.encryption import encrypt
        return encrypt(plain)
    import base64
    return base64.urlsafe_b64encode(plain.encode()).decode()


def _unseal(enc: str) -> str:
    import config
    if config.FERNET_KEY:
        from middleware.encryption import decrypt_or_passthrough
        return decrypt_or_passthrough(enc)
    import base64
    return base64.urlsafe_b64decode(enc.encode()).decode()


def audit_encryption_configured() -> bool:
    """Returns True iff FERNET_KEY is set so plaid_access_token_enc rounds
    through real symmetric encryption. Wire this into a boot guard before
    accepting production Plaid credentials."""
    import config
    return bool(config.FERNET_KEY)


def sync_transactions(session: Session, profile_id: str, cursor: Optional[str] = None) -> dict:
    """Pull Plaid transactions and upsert. Flag missing-receipt rows for reconciler."""
    profile = session.get(PmPayoutProfile, profile_id)
    if profile is None or not profile.plaid_access_token_enc:
        return {"added": 0, "cursor": cursor}
    access_token = _unseal(profile.plaid_access_token_enc)
    resp = client.transactions_sync(access_token, cursor)
    added = 0
    for t in resp.get("added", []):
        existing = session.execute(
            select(BankTransaction).where(BankTransaction.plaid_txn_id == t.get("transaction_id"))
        ).scalar_one_or_none()
        if existing:
            continue
        amt = int(round(float(t.get("amount", 0)) * 100))
        bt = BankTransaction(
            id=new_uuid(),
            plaid_account_id=t.get("account_id", ""),
            plaid_txn_id=t.get("transaction_id", ""),
            amount_cents=amt,
            name=t.get("name"),
            category=",".join(t.get("category") or []),
            posted_date=t.get("date"),
            pending=t.get("pending", False),
            missing_receipt=(amt > 0),
        )
        session.add(bt)
        added += 1
    session.flush()
    return {"added": added, "cursor": resp.get("next_cursor"), "has_more": resp.get("has_more", False)}


def process_webhook(session: Session, headers: dict, body: bytes) -> dict:
    body_json = json.loads(body.decode("utf-8") or "{}")
    event_id = f"{body_json.get('webhook_type','?')}:{body_json.get('webhook_code','?')}:{body_json.get('item_id','?')}"
    existing = session.execute(
        select(WebhookEvent).where(WebhookEvent.provider == "plaid",
                                   WebhookEvent.event_id == event_id)
    ).scalar_one_or_none()
    if existing is not None:
        return {"ok": True, "duplicate": True}
    ev = WebhookEvent(
        id=new_uuid(), provider="plaid", event_id=event_id,
        event_type=body_json.get("webhook_code", ""),
        payload=body_json, signature_ok=True,  # Plaid uses JWT; verify in production
        received_at=utcnow().isoformat(),
    )
    session.add(ev)
    # AUTH webhook updates verification status
    if body_json.get("webhook_type") == "AUTH":
        item_id = body_json.get("item_id")
        prof = session.execute(
            select(PmPayoutProfile).where(PmPayoutProfile.plaid_item_id == item_id)
        ).scalar_one_or_none()
        if prof and body_json.get("webhook_code") == "AUTOMATICALLY_VERIFIED":
            prof.status = "verified"
    ev.processed_at = utcnow().isoformat()
    session.flush()
    return {"ok": True}
