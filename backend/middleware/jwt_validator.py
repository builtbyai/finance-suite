"""Optional second auth layer: verify the Worker-issued JWT presented by the
end-user, on top of the HMAC server-to-server gate.

Today the Worker forwards the end-user's JWT in the X-User-JWT header (the
Authorization header is consumed by HMAC). Routes that want per-user audit
trail (created_by/updated_by) read flask.g.user after calling
@require_user_jwt.

If CRM_JWT_SECRET is unset, the decorator is a no-op — request still
succeeds, but g.user is None. Production deployments should set it.
"""
from __future__ import annotations

from functools import wraps

from flask import g, request, jsonify

import jwt as pyjwt  # PyJWT

import config


def _verify(token: str) -> dict | None:
    secret = config.CRM_JWT_SECRET
    if not secret:
        return None
    try:
        return pyjwt.decode(token, secret, algorithms=["HS256"])
    except pyjwt.PyJWTError:
        return None


def require_user_jwt(fn):
    """Soft requirement: g.user is populated if a valid JWT is presented; if
    CRM_JWT_SECRET is not configured, every request is allowed but
    g.user stays None (single-user / pre-deploy mode)."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-User-JWT", "")
        if not token:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
        payload = _verify(token) if token else None
        if config.CRM_JWT_SECRET and not payload:
            return jsonify({"error": "user jwt required"}), 401
        g.user = payload
        return fn(*args, **kwargs)

    return wrapper
