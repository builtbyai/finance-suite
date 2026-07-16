"""Fernet symmetric encryption for at-rest secrets (Plaid access tokens).

Per BUILD-SPEC: plaid_access_token_enc is column-named "encrypted" but the
generation step was never wired. This helper makes the contract real.

Set FERNET_KEY in env. Generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

If FERNET_KEY is missing, the helpers raise — callers must check before
storing tokens. Reading legacy plaintext rows is supported via
decrypt_or_passthrough() during the migration window.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

import config


def _key() -> bytes:
    if not config.FERNET_KEY:
        raise RuntimeError("FERNET_KEY not configured")
    return config.FERNET_KEY.encode("utf-8")


def encrypt(plaintext: str) -> str:
    return Fernet(_key()).encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    return Fernet(_key()).decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def decrypt_or_passthrough(value: str | None) -> str | None:
    """Decrypt if possible; otherwise return the value as-is. Use during the
    migration window where some rows are still plaintext from before
    FERNET_KEY was set. Once the backfill is complete, switch callers to
    decrypt() so a bad ciphertext raises instead of leaking plaintext."""
    if value is None or value == "":
        return value
    if not config.FERNET_KEY:
        return value
    try:
        return Fernet(_key()).decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return value
