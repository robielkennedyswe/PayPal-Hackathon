"""Test setup: isolated data dir, mock AI, no network.

Env vars must be set before any app module is imported, because db.py and
main.py read them at import time.
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="shopmcp-test-")
os.environ["AI_PROVIDER"] = "mock"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from app import ai_budget, ai_provider, paypal  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    # Fresh tables per test so tests can't leak state into each other.
    SQLModel.metadata.drop_all(engine)
    # localhost base URL: the MCP endpoint rejects unknown Host headers
    # (DNS-rebinding protection), and TestClient defaults to "testserver".
    with TestClient(app, base_url="http://localhost:8000") as c:  # runs lifespan
        yield c


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if a test reaches PayPal without explicitly faking it."""

    def _blocked(*_a, **_k):
        raise AssertionError("unexpected real PayPal call in tests")

    for name in ("get_access_token", "create_order", "capture_order", "get_order"):
        monkeypatch.setattr(paypal, name, _blocked)

    def _no_claude():
        raise AssertionError("unexpected real Claude API call in tests")

    monkeypatch.setattr(ai_provider, "client", _no_claude)
    # Fresh per-visitor rate-limit windows per test.
    ai_budget._client_calls.clear()
