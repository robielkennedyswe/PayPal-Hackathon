"""Single switch for which AI backend the app uses.

Every AI feature (catalog vision, shopper agent) asks this module which
provider is active, so moving from mock to the real Claude API is a .env
change (AI_PROVIDER=anthropic, AI_MODEL=..., ANTHROPIC_API_KEY=...), not a
code change elsewhere.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

Provider = Literal["mock", "anthropic"]
_VALID: tuple[Provider, ...] = ("mock", "anthropic")


def provider() -> Provider:
    """Active provider from AI_PROVIDER (default "mock"). Unknown values fail loudly."""
    value = (os.getenv("AI_PROVIDER") or "mock").strip().lower()
    if value not in _VALID:
        raise RuntimeError(f"AI_PROVIDER must be one of {_VALID}, got {value!r}")
    if value == "anthropic":
        # Check config up front so a misconfigured deploy fails at the first
        # AI call with a clear message, not deep inside an SDK.
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError("AI_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
        if not os.getenv("AI_MODEL"):
            raise RuntimeError("AI_PROVIDER=anthropic but AI_MODEL is not set")
    return value  # type: ignore[return-value]


def model() -> str | None:
    """Model id for the real API (None in mock mode)."""
    return os.getenv("AI_MODEL") or None


def is_mock() -> bool:
    return provider() == "mock"


# ---------- Claude API (AI_PROVIDER=anthropic) ----------
# Every Claude request in the app goes through create_message(), so the cost
# limiter (ai_budget.py) can't be bypassed by a new feature.

# Models that support the server-side refusal fallback ("fallbacks":
# "default"): if the model declines a request on safety grounds, the API
# re-runs it on a fallback model inside the same call instead of failing.
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client = None


def client():
    """Shared Anthropic client. The SDK reads ANTHROPIC_API_KEY itself; the
    key is never logged or passed around in our code."""
    global _client
    if _client is None:
        import anthropic  # imported lazily so mock mode works without the SDK configured

        # 60s timeout and 1 retry: a stuck call shouldn't hang the chat, and
        # each retry is a billed attempt.
        _client = anthropic.Anthropic(timeout=60.0, max_retries=1)
    return _client


def create_message(*, client_key: str | None = None, **params):
    """One Claude Messages API call, budget-checked and usage-recorded.

    Raises ai_budget.AIBudgetExceeded (before any request) when a limit is
    hit, and the SDK's anthropic.APIError subclasses on API failures.
    """
    from app import ai_budget

    m = model()
    ai_budget.reserve(client_key)
    extra = {"betas": [_FALLBACK_BETA], "fallbacks": "default"} if m in _FALLBACK_MODELS else {}
    response = client().beta.messages.create(model=m, **extra, **params)
    ai_budget.record(m, response.usage)
    return response
