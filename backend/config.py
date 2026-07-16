"""Runtime configuration. Reads .env from project root."""
import os
from pathlib import Path

if not os.getenv("APP_SKIP_DOTENV"):
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    except ImportError:
        pass


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{(DATA_DIR / 'finance.db').as_posix()}"
IS_SQLITE = DATABASE_URL.startswith("sqlite")

HOST = os.getenv("BIND_HOST", "127.0.0.1")
PORT = int(os.getenv("BIND_PORT", "5055"))

# Provider settings (all optional — services run in dry_run mode if missing)
PAYPAL_BASE = os.getenv("PAYPAL_BASE", "https://api-m.sandbox.paypal.com")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_WEBHOOK_ID = os.getenv("PAYPAL_WEBHOOK_ID", "")

PLAID_BASE = os.getenv("PLAID_BASE", "https://sandbox.plaid.com")
PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID", "")
PLAID_SECRET = os.getenv("PLAID_SECRET", "")

DWOLLA_BASE = os.getenv("DWOLLA_BASE", "https://api-sandbox.dwolla.com")
DWOLLA_KEY = os.getenv("DWOLLA_KEY", "")
DWOLLA_SECRET = os.getenv("DWOLLA_SECRET", "")
DWOLLA_MASTER_FS = os.getenv("DWOLLA_MASTER_FUNDING_SOURCE", "")
DWOLLA_WEBHOOK_SECRET = os.getenv("DWOLLA_WEBHOOK_SECRET", "")

PRINTIFY_KEY = os.getenv("PRINTIFY_KEY", "")
PRINTFUL_KEY = os.getenv("PRINTFUL_KEY", "")


FORCE_DRY_RUN = os.getenv("APP_FORCE_DRY_RUN", "").lower() in ("1", "true", "yes")


# CRM Worker bridge.
#   CRM_API_BASE_URL  — where to POST PayPal-paid webhooks back to. e.g.
#                            https://api.example.com
#   FINANCE_RELAY_SECRET   — shared HMAC secret. The Worker holds the matching
#                            value as env.FINANCE_RELAY_SECRET. Required for any
#                            /api/internal/* route to accept a request and for
#                            us to send outbound webhooks. Boot fails fast if
#                            missing in non-dev environments.
#   CRM_JWT_SECRET    — used to verify Worker-issued JWTs presented by the
#                            end user (optional second auth layer on top of the
#                            HMAC server-to-server gate). Optional today.
#   FERNET_KEY             — symmetric key for at-rest encryption of
#                            plaid_access_token_enc. Generated via
#                            `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
CRM_API_BASE_URL = os.getenv("CRM_API_BASE_URL", "")
FINANCE_RELAY_SECRET = os.getenv("FINANCE_RELAY_SECRET", "")
CRM_JWT_SECRET = os.getenv("CRM_JWT_SECRET", "")
FERNET_KEY = os.getenv("FERNET_KEY", "")


def has_paypal() -> bool:
    if FORCE_DRY_RUN:
        return False
    return bool(PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET)


def has_plaid() -> bool:
    if FORCE_DRY_RUN:
        return False
    return bool(PLAID_CLIENT_ID and PLAID_SECRET)


def has_dwolla() -> bool:
    if FORCE_DRY_RUN:
        return False
    return bool(DWOLLA_KEY and DWOLLA_SECRET)
