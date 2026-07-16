"""Use a temp SQLite DB for every test session.

Important: set DATABASE_URL *before* any project module is imported.
"""
import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"

# Tests run in dry_run mode regardless of the host shell environment.
for _k in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID",
          "PLAID_CLIENT_ID", "PLAID_SECRET",
          "DWOLLA_KEY", "DWOLLA_SECRET", "DWOLLA_WEBHOOK_SECRET",
          "DWOLLA_MASTER_FUNDING_SOURCE",
          "PRINTIFY_KEY", "PRINTFUL_KEY"):
    os.environ.pop(_k, None)
# Defensively also disable .env auto-load:
os.environ["APP_SKIP_DOTENV"] = "1"

import pytest

# These imports will read the env var we just set.
from db import Base, engine, session_scope  # noqa: E402
import models  # noqa: F401, E402
from seed import run as run_seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_db():
    Base.metadata.create_all(engine)
    run_seed()
    yield


@pytest.fixture
def session():
    with session_scope() as s:
        yield s
