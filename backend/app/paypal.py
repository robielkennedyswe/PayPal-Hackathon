"""Thin PayPal Orders v2 client (sandbox only).

Credentials come from the environment (.env at the repo root). The access
token is cached in memory and reused until shortly before it expires, so we
make one OAuth call per ~9 hours instead of one per request.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

# .env lives at the repo root: backend/app/paypal.py -> parents[2]
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

SANDBOX_URL = "https://api-m.sandbox.paypal.com"
BASE_URL = os.getenv("PAYPAL_BASE_URL") or SANDBOX_URL
from app.config import APP_BASE_URL  # noqa: E402  (after load_dotenv above)

# Hard rule: sandbox only. Refuse to run against anything else.
if "sandbox" not in BASE_URL:
    raise RuntimeError(f"PAYPAL_BASE_URL must be a sandbox URL, got {BASE_URL!r}")

_TOKEN_SAFETY_MARGIN_S = 60  # refresh a minute early to avoid edge-of-expiry 401s
_token: str | None = None
_token_expires_at: float = 0.0


class PayPalError(RuntimeError):
    """Raised for non-2xx PayPal responses. Carries PayPal's debug_id for support."""

    def __init__(self, status: int, body: dict | str):
        self.status = status
        self.body = body
        debug_id = body.get("debug_id") if isinstance(body, dict) else None
        name = body.get("name") if isinstance(body, dict) else None
        super().__init__(f"PayPal {status} {name or ''} (debug_id={debug_id})".strip())


def _credentials() -> tuple[str, str]:
    # strip(): a pasted secret with a trailing newline would break the request.
    client_id = (os.getenv("Client_ID") or "").strip()
    secret = (os.getenv("Secret_Key") or "").strip()
    if not client_id or not secret:
        raise RuntimeError("Client_ID / Secret_Key missing from environment (.env)")
    return client_id, secret


def get_access_token() -> str:
    """Return a cached bearer token, fetching a new one if missing or near expiry."""
    global _token, _token_expires_at
    if _token and time.time() < _token_expires_at:
        return _token

    resp = httpx.post(
        f"{BASE_URL}/v1/oauth2/token",
        auth=_credentials(),
        data={"grant_type": "client_credentials"},
        timeout=20,
    )
    _raise_for_status(resp)
    data = resp.json()
    _token = data["access_token"]
    _token_expires_at = time.time() + int(data["expires_in"]) - _TOKEN_SAFETY_MARGIN_S
    return _token


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    raise PayPalError(resp.status_code, body)


def _request(method: str, path: str, json: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json",
    }
    if method == "POST":
        # Idempotency key: if a POST is retried, PayPal won't create a duplicate.
        headers["PayPal-Request-Id"] = str(uuid.uuid4())
    resp = httpx.request(method, f"{BASE_URL}{path}", headers=headers, json=json, timeout=30)
    _raise_for_status(resp)
    return resp.json() if resp.content else {}


def create_order(
    amount: str,
    currency: str = "USD",
    *,
    description: str | None = None,
    payee_email: str | None = None,
    item: dict | None = None,
    return_url: str | None = None,
    cancel_url: str | None = None,
) -> dict:
    """Create a CAPTURE-intent order. `amount` is a decimal string like "34.00".

    payee_email routes the money to the seller's sandbox business account
    instead of the app's own account (Orders v2 `purchase_units[].payee`,
    verified in the v2.36 spec). PayPal does NOT validate the email at create
    time: any address is accepted, so a typo only surfaces at approval/capture.

    item = {"name", "quantity": int, "unit_amount": "12.00"} adds a line item
    so the buyer's PayPal approval page shows what they're paying for.
    PayPal then requires amount.breakdown.item_total, which must equal
    unit_amount * quantity (we have no tax/shipping, so it equals amount).
    """
    unit: dict = {"amount": {"currency_code": currency, "value": amount}}
    if description:
        unit["description"] = description[:127]  # PayPal caps description at 127 chars
    if payee_email:
        unit["payee"] = {"email_address": payee_email}
    if item:
        unit["items"] = [{
            "name": item["name"][:127],
            "quantity": str(item["quantity"]),  # PayPal wants a string here
            "unit_amount": {"currency_code": currency, "value": item["unit_amount"]},
            "category": "PHYSICAL_GOODS",
        }]
        unit["amount"]["breakdown"] = {"item_total": {"currency_code": currency, "value": amount}}

    body = {
        "intent": "CAPTURE",
        "purchase_units": [unit],
        # experience_context is the current way to set return/cancel URLs.
        # With it, PayPal returns the approval link as rel="payer-action".
        "payment_source": {
            "paypal": {
                "experience_context": {
                    "user_action": "PAY_NOW",
                    "shipping_preference": "NO_SHIPPING",
                    "return_url": return_url or f"{APP_BASE_URL}/paypal/return",
                    "cancel_url": cancel_url or f"{APP_BASE_URL}/paypal/cancel",
                }
            }
        },
    }
    return _request("POST", "/v2/checkout/orders", json=body)


def get_order(order_id: str) -> dict:
    return _request("GET", f"/v2/checkout/orders/{order_id}")


def capture_order(order_id: str) -> dict:
    """Capture an APPROVED order. Returns status COMPLETED on success."""
    return _request("POST", f"/v2/checkout/orders/{order_id}/capture", json={})


def approve_url(order: dict) -> str | None:
    """Pull the buyer approval link out of an order response."""
    for link in order.get("links", []):
        if link.get("rel") in ("payer-action", "approve"):
            return link["href"]
    return None
