"""Public URLs and deployment settings, resolved once from the environment.

Local dev (defaults): API on :8000, Vite dev server on :5173.
Render: RENDER_EXTERNAL_URL (set automatically, e.g. https://shopmcp.onrender.com)
is the default APP_BASE_URL, and when the built frontend is served by this
app (FRONTEND_DIST set, as in the Dockerfile) FRONTEND_URL defaults to the
same origin. Explicit APP_BASE_URL / FRONTEND_URL always win.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _url(value: str | None) -> str | None:
    return value.rstrip("/") if value else None


def resolve(env) -> tuple[str, str | None, str]:
    """(APP_BASE_URL, FRONTEND_DIST, FRONTEND_URL) from an environment mapping."""
    app_base = _url(env.get("APP_BASE_URL")) or _url(env.get("RENDER_EXTERNAL_URL")) or "http://localhost:8000"
    dist = env.get("FRONTEND_DIST") or None
    frontend = _url(env.get("FRONTEND_URL")) or (app_base if dist else "http://localhost:5173")
    return app_base, dist, frontend


# APP_BASE_URL: where the backend is publicly reachable (PayPal return URLs, MCP).
# FRONTEND_DIST: built frontend to serve from this app (set by the Dockerfile;
#   unset in local dev, where Vite serves the frontend).
# FRONTEND_URL: where the browser app lives (PayPal redirects land on /checkout/result).
APP_BASE_URL, FRONTEND_DIST, FRONTEND_URL = resolve(os.environ)
