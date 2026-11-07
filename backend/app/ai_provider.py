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
