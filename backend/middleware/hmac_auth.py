"""HMAC-SHA256 verification of inbound requests from the CRM Worker.

The Worker signs every request with the scheme:
    HMAC-SHA256( ts + "." + nonce + "." + raw_body ) -> hex

and presents three headers:
    X-Timestamp / X-Nonce / X-Signature

Replay window: +/-60s on the timestamp. Nonces should be single-use per
window; we keep that responsibility in the caller for now (the Worker
re-uses nonces only at very low risk, but a future hardening pass would
move the nonce dedup behind Redis or a local cache).

Usage:
    from middleware.hmac_auth import require_worker_hmac

    @app.post("/api/internal/customers/upsert")
    @require_worker_hmac
    def upsert():
        ...

The decorator reads the raw body once and stashes it on `flask.g` as
`worker_raw_body` so route handlers can re-parse without consuming the
stream twice.
"""
from __future__ import annotations

import hmac
import hashlib
import time
from functools import wraps

from flask import g, request, jsonify

import config

REPLAY_WINDOW_MS = 60_000


def _safe_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def verify_signature(raw_body: bytes, ts: str, nonce: str, sig: str, secret: str) -> tuple[bool, str]:
    if not secret:
        return False, "FINANCE_RELAY_SECRET not configured"
    if not ts or not nonce or not sig:
        return False, "missing auth headers"
    try:
        ts_num = int(ts)
    except ValueError:
        return False, "bad timestamp"
    now_ms = int(time.time() * 1000)
    if abs(now_ms - ts_num) > REPLAY_WINDOW_MS:
        return False, "replay window expired"

    payload = f"{ts}.{nonce}.".encode("utf-8") + raw_body
    mac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    if not _safe_eq(mac, sig):
        return False, "bad signature"
    return True, ""


def require_worker_hmac(fn):
    """Flask route decorator. Rejects with 401 on signature failure."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        raw = request.get_data(cache=True) or b""
        ts = request.headers.get("X-Timestamp", "")
        nonce = request.headers.get("X-Nonce", "")
        sig = request.headers.get("X-Signature", "")
        ok, err = verify_signature(raw, ts, nonce, sig, config.FINANCE_RELAY_SECRET)
        if not ok:
            return jsonify({"error": err}), 401
        g.worker_raw_body = raw
        g.worker_nonce = nonce
        return fn(*args, **kwargs)

    return wrapper
