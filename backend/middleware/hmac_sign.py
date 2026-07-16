"""Outbound HMAC signer — used to call the CRM Worker back when we
receive a PayPal-paid webhook and need to notify the CRM.

Mirrors the Worker's signOutbound() in worker-backend/src/routes/finance.js.
"""
from __future__ import annotations

import hmac
import hashlib
import secrets
import time

import requests

import config


def _new_nonce() -> str:
    return secrets.token_hex(8)


def sign_outbound(secret: str, raw_body: bytes) -> dict[str, str]:
    ts = str(int(time.time() * 1000))
    nonce = _new_nonce()
    payload = f"{ts}.{nonce}.".encode("utf-8") + raw_body
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return {"X-Timestamp": ts, "X-Nonce": nonce, "X-Signature": sig}


def post_to_worker(path: str, payload: dict, *, timeout: float = 15.0) -> requests.Response:
    """Send a POST to the Worker with HMAC headers. Raises if config missing.

    `path` is the path on the Worker, e.g. "/api/finance/webhook/paypal-paid".
    """
    base = config.CRM_API_BASE_URL.rstrip("/")
    secret = config.FINANCE_RELAY_SECRET
    if not base:
        raise RuntimeError("CRM_API_BASE_URL not configured")
    if not secret:
        raise RuntimeError("FINANCE_RELAY_SECRET not configured")

    raw = (b"" if payload is None else __import__("json").dumps(payload).encode("utf-8"))
    headers = {"Content-Type": "application/json", **sign_outbound(secret, raw)}
    return requests.post(base + path, data=raw, headers=headers, timeout=timeout)
