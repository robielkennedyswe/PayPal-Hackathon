"""Cost limiter for the Claude API.

Every Claude call goes through ai_provider.create_message(), which calls
reserve() before the request and record() after it. Four limits, all from
.env (defaults below suit a hackathon demo):

    AI_DAILY_BUDGET_USD          estimated spend per UTC day     (default 5.00)
    AI_TOTAL_BUDGET_USD          estimated spend, all days        (default 25.00)
    AI_DAILY_CALL_LIMIT          API calls per UTC day            (default 300)
    AI_CLIENT_HOURLY_CALL_LIMIT  API calls per visitor per hour   (default 40)

Spend is an *estimate* (token counts x list price), so also set a hard
monthly spend limit in the Claude Console; that's the real backstop.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from sqlalchemy import func, update
from sqlalchemy.dialects.sqlite import insert
from sqlmodel import Session, select

from app.db import engine
from app.models import AIUsage

# List prices, USD per million tokens (input, output). Cache writes bill at
# 1.25x input and cache reads at 0.1x input.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5": (5.00, 25.00),
    "claude-fable-5-1": (10.00, 50.00),
}
# Unknown model: assume the most expensive tier so the budget errs safe.
_UNKNOWN_PRICE = (10.00, 50.00)


class AIBudgetExceeded(Exception):
    """A limit is hit. `message` is safe to show visitors."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


def limits() -> dict:
    # Read on every call so tests (and a changed .env + restart) apply.
    return {
        "daily_budget_usd": _env_float("AI_DAILY_BUDGET_USD", 5.00),
        "total_budget_usd": _env_float("AI_TOTAL_BUDGET_USD", 25.00),
        "daily_call_limit": int(_env_float("AI_DAILY_CALL_LIMIT", 300)),
        "client_hourly_call_limit": int(_env_float("AI_CLIENT_HOURLY_CALL_LIMIT", 40)),
    }


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------- per-visitor rate limit (in memory) ----------
# In memory is fine: one Render instance, and losing it on restart only
# resets a 1-hour window. The global budgets above are persisted.

_WINDOW_S = 3600
_client_calls: dict[str, deque[float]] = defaultdict(deque)
_client_lock = threading.Lock()


def _take_client_slot(client_key: str | None, limit: int) -> None:
    if not client_key:
        return  # internal callers (scripts) have no visitor to limit
    now = time.monotonic()
    with _client_lock:
        calls = _client_calls[client_key]
        while calls and now - calls[0] > _WINDOW_S:
            calls.popleft()
        if len(calls) >= limit:
            raise AIBudgetExceeded(
                "You've reached this demo's hourly AI limit. Please try again in a little while."
            )
        calls.append(now)


# ---------- global budgets (persisted) ----------

def reserve(client_key: str | None = None) -> None:
    """Claim one API call, or raise AIBudgetExceeded. Call before every request."""
    lim = limits()
    _take_client_slot(client_key, lim["client_hourly_call_limit"])

    day = _today()
    with Session(engine) as s:
        s.exec(insert(AIUsage).values(day=day).on_conflict_do_nothing())
        total = s.exec(select(func.coalesce(func.sum(AIUsage.cost_usd), 0.0))).one()
        if total >= lim["total_budget_usd"]:
            s.commit()
            raise AIBudgetExceeded("This demo has used its AI budget. The AI features are paused.")
        # Atomic check-and-increment: concurrent requests can't both slip
        # under the call limit, because only rows still under it are updated.
        claimed = s.exec(
            update(AIUsage)
            .where(
                AIUsage.day == day,
                AIUsage.calls < lim["daily_call_limit"],
                AIUsage.cost_usd < lim["daily_budget_usd"],
            )
            .values(calls=AIUsage.calls + 1)
        ).rowcount
        s.commit()
    if claimed != 1:
        raise AIBudgetExceeded("This demo has reached today's AI usage limit. Please try again tomorrow.")


def record(model: str, usage: object) -> float:
    """Add a response's token usage to today's totals; returns its estimated cost."""
    tokens_in = getattr(usage, "input_tokens", 0) or 0
    tokens_out = getattr(usage, "output_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0

    price_in, price_out = PRICES.get(model, _UNKNOWN_PRICE)
    cost = (tokens_in * price_in + cache_write * price_in * 1.25 + cache_read * price_in * 0.1
            + tokens_out * price_out) / 1_000_000

    with Session(engine) as s:
        s.exec(insert(AIUsage).values(day=_today()).on_conflict_do_nothing())
        s.exec(
            update(AIUsage)
            .where(AIUsage.day == _today())
            .values(
                input_tokens=AIUsage.input_tokens + tokens_in + cache_write + cache_read,
                output_tokens=AIUsage.output_tokens + tokens_out,
                cost_usd=AIUsage.cost_usd + cost,
            )
        )
        s.commit()
    return cost


def status() -> dict:
    """Today's usage vs. limits (for /api/ai/usage and the dashboard)."""
    with Session(engine) as s:
        row = s.get(AIUsage, _today())
        total = s.exec(select(func.coalesce(func.sum(AIUsage.cost_usd), 0.0))).one()
    return {
        "today": {
            "calls": row.calls if row else 0,
            "input_tokens": row.input_tokens if row else 0,
            "output_tokens": row.output_tokens if row else 0,
            "cost_usd": round(row.cost_usd, 4) if row else 0.0,
        },
        "total_cost_usd": round(total, 4),
        "limits": limits(),
    }
