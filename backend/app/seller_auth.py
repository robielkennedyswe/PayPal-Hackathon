"""Seller tokens: the only thing that lets someone manage a shop.

There are no accounts. Creating a shop returns a random token once; the
seller's browser keeps it and sends it as the X-Seller-Token header on every
seller route (upload, edit, delete, publish, dashboard). Shop and product ids
are public (storefront JSON, photo URLs), so the token, not the id, is what
proves ownership.

Only a SHA-256 hash is stored, so a leaked database doesn't leak working
tokens. (A plain hash is fine here: the token is 256 random bits, so it
can't be brute-forced the way a password could.)

Issue a new token for an existing shop (e.g. one created before tokens
existed), from backend/ (on Render: the service's Shell tab, in /app/backend):
    python -m app.seller_auth <shop_id>
This replaces any previous token and prints a seller link to open the shop.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

HEADER = "X-Seller-Token"
NO_ACCESS = (
    "Seller access required. Open this shop in the browser that created it, "
    "or use its seller link."
)


def new_token() -> tuple[str, str]:
    """(token for the seller, hash to store)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def matches(token: str | None, stored_hash: str | None) -> bool:
    """Constant-time check. A shop with no stored hash never matches (fail closed)."""
    if not token or not stored_hash:
        return False
    return hmac.compare_digest(hash_token(token), stored_hash)


def seller_link(base_url: str, shop_id: str, token: str) -> str:
    # The token goes in the #fragment: browsers never send it to the server,
    # so it stays out of access logs and Referer headers.
    return f"{base_url.rstrip('/')}/sell/{shop_id}/dashboard#seller={token}"


def _issue(shop_id: str) -> None:
    from sqlmodel import Session

    from app import config
    from app.db import engine, init_db
    from app.models import Shop

    init_db()  # adds the token column if this database predates it
    with Session(engine) as session:
        shop = session.get(Shop, shop_id)
        if shop is None:
            raise SystemExit(f"No shop with id {shop_id}")
        token, shop.seller_token_hash = new_token()
        session.add(shop)
        session.commit()
        base = config.FRONTEND_URL or config.APP_BASE_URL
        print(f"New seller token for {shop.name} ({shop_id}); any previous token no longer works.")
        print("Open this link in the seller's browser (keep it private, it grants full control):")
        print(seller_link(base, shop_id, token))


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.seller_auth <shop_id>")
    _issue(sys.argv[1])
