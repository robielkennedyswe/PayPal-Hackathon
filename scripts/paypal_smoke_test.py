"""End-to-end PayPal sandbox check: token -> create order -> approve -> capture.

Run from the repo root:
    backend/.venv/bin/python scripts/paypal_smoke_test.py

Open the printed approve link, log in as the *sandbox personal (buyer)*
account, and approve. The script polls the order and captures it as soon as
it is APPROVED. After approval PayPal redirects to APP_BASE_URL/paypal/return,
which won't load yet (no server running). That's expected; ignore it.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import paypal  # noqa: E402

POLL_EVERY_S = 3
TIMEOUT_S = 10 * 60


def main() -> int:
    paypal.get_access_token()  # fail fast on bad credentials; never print the token
    print(f"OAuth OK against {paypal.BASE_URL}")

    order = paypal.create_order("34.00", "USD", description="ShopMCP smoke test")
    order_id = order["id"]
    print(f"Created order {order_id} (status {order['status']})")
    print(f"\nApprove as the sandbox buyer:\n  {paypal.approve_url(order)}\n")

    print("Waiting for approval", end="", flush=True)
    deadline = time.time() + TIMEOUT_S
    while True:
        status = paypal.get_order(order_id)["status"]
        if status == "APPROVED":
            break
        if time.time() > deadline:
            print(f"\nTimed out after {TIMEOUT_S // 60} min (status {status}).")
            return 1
        print(".", end="", flush=True)
        time.sleep(POLL_EVERY_S)

    print("\nApproved. Capturing...")
    result = paypal.capture_order(order_id)
    capture = result["purchase_units"][0]["payments"]["captures"][0]
    payer = result.get("payer", {})
    print(f"Order status:   {result['status']}")
    print(f"Capture id:     {capture['id']} ({capture['status']})")
    print(f"Amount:         {capture['amount']['value']} {capture['amount']['currency_code']}")
    print(f"Payer:          {payer.get('email_address', '?')}")
    return 0 if result["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except paypal.PayPalError as e:
        print(f"\n{e}\n{e.body}")
        sys.exit(1)
