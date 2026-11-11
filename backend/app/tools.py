"""The four shopping tools, as plain functions.

These are the single source of truth for what an AI agent can do. Two
callers share them:
- mcp_server.py exposes them to any MCP client (Claude Code, Claude Desktop…)
- agent.py (built-in shopper agent) calls them directly via Claude tool use

Every function takes a DB session and returns JSON-ready dicts. Expected
failures (bad id, out of stock…) raise checkout.CheckoutError with a stable
`code` and a message safe to show an agent; callers translate that into their
own error format.

Only *live* products in *published* shops are ever visible here (a photo
added to a live shop stays hidden until the seller clicks Save changes).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from sqlmodel import Session, select

from app import activity, checkout, config, paypal
from app.checkout import CheckoutError, Outcome
from app.models import Order, OrderStatus, Product, Shop

MAX_RESULTS = 10
_SHORT_DESC_CHARS = 140


# ---------- search_products ----------

def search_products(session: Session, query: str = "", max_price: float | None = None) -> list[dict]:
    """Keyword search over published products, best match first.

    Scoring is deliberately simple (catalogs are tiny): each query word that
    appears in the title scores 3, in tags 2, in description/attributes 1.
    An empty query lists everything. In-stock items sort before sold-out ones.
    """
    limit = _price_limit(max_price)
    words = _words(query)

    rows = session.exec(
        select(Product, Shop)
        .join(Shop, Shop.id == Product.shop_id)
        .where(Shop.published == True, Product.live == True)  # noqa: E712
    ).all()

    scored = []
    for product, shop in rows:
        if limit is not None and Decimal(product.price) > limit:
            continue
        score = _score(product, words) if words else 1
        if score > 0:
            scored.append((score, product, shop))

    # Sort: in stock first, then relevance, then cheaper first.
    scored.sort(key=lambda t: (t[1].stock <= 0, -t[0], Decimal(t[1].price)))
    top = scored[:MAX_RESULTS]
    results = [_summary(p, s) for _, p, s in top]  # built before record() commits

    # One "search" event per shop that appeared in the results.
    per_shop: dict[str, list[str]] = {}
    for _, p, s in top:
        per_shop.setdefault(s.id, []).append(p.title)
    for shop_id, titles in per_shop.items():
        activity.record(session, shop_id=shop_id, kind="search",
                        detail={"query": query, "max_price": max_price, "matches": len(titles), "top": titles[0]})
    return results


def _price_limit(max_price: float | None) -> Decimal | None:
    if max_price is None:
        return None
    try:
        # str() first so 25.1 becomes Decimal("25.1"), not 25.0999999…
        limit = Decimal(str(max_price))
    except InvalidOperation:
        raise CheckoutError("INVALID_PRICE", "max_price must be a number") from None
    if limit <= 0:
        raise CheckoutError("INVALID_PRICE", "max_price must be greater than 0")
    return limit


def _words(text: str) -> set[str]:
    # Lowercase alphanumeric words, plus a naive singular form so "mugs"
    # matches "mug". Good enough for a hackathon catalog.
    words = set(re.findall(r"[a-z0-9]+", (text or "").lower()))
    return words | {w[:-1] for w in words if len(w) > 3 and w.endswith("s")}


def _score(product: Product, words: set[str]) -> int:
    title = _words(product.title)
    tags = _words(" ".join(product.tags))
    rest = _words(product.description + " " + " ".join(f"{k} {v}" for k, v in product.attributes.items()))
    return sum(3 * (w in title) + 2 * (w in tags) + (w in rest) for w in words)


# Agents (ChatGPT, Claude, ...) can only show what the tools give them, so
# photos and the storefront are full https links, not app-relative paths.
SHIPPING_AND_TAX = "Included: the PayPal total is price × quantity, with no shipping or tax added."


def _image_url(p: Product) -> str | None:
    return f"{config.APP_BASE_URL}/uploads/{p.image_path}" if p.image_path else None


def _shop_info(s: Shop) -> dict:
    return {"name": s.name, "slug": s.slug, "url": f"{config.FRONTEND_URL}/s/{s.slug}"}


def _summary(p: Product, s: Shop) -> dict:
    return {
        "id": p.id,
        "title": p.title,
        "price": {"value": p.price, "currency": checkout.CURRENCY},
        "shop": _shop_info(s),
        "short_description": _shorten(p.description),
        "stock": p.stock,
        "available": p.stock > 0,
        "image_url": _image_url(p),
    }


def _shorten(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _SHORT_DESC_CHARS else text[: _SHORT_DESC_CHARS - 1].rstrip() + "…"


# ---------- get_product ----------

def get_product(session: Session, product_id: str) -> dict:
    """Full listing. Shape must match frontend/src/agentView.ts, which shows
    sellers exactly what agents receive."""
    product = session.get(Product, product_id)
    shop = session.get(Shop, product.shop_id) if product else None
    if product is None or shop is None or not (shop.published and product.live):
        raise CheckoutError("PRODUCT_NOT_FOUND", f"No product with id {product_id!r}")
    listing = {
        "id": product.id,
        "title": product.title,
        "description": product.description,
        "price": {"value": product.price, "currency": checkout.CURRENCY},
        "shipping_and_tax": SHIPPING_AND_TAX,
        "stock": product.stock,
        "available": product.stock > 0,
        "attributes": product.attributes,
        "tags": product.tags,
        "image_url": _image_url(product),
        "shop": _shop_info(shop),
        "checkout": "Call create_checkout; the buyer approves payment in PayPal.",
    }
    activity.record(session, shop_id=shop.id, kind="view", product_id=product.id, detail={"title": product.title})
    return listing


# ---------- create_checkout ----------

def create_checkout(session: Session, product_id: str, qty: int = 1) -> dict:
    return checkout.create_checkout(session, product_id, qty)


# ---------- get_order_status ----------

_STATUS_MESSAGES = {
    OrderStatus.CREATED: "Waiting for the buyer to approve the payment in PayPal using the approve_url.",
    OrderStatus.APPROVED: "The buyer approved; the payment is being captured. Check again shortly.",
    OrderStatus.COMPLETED: "Paid. The payment was captured and the sale is complete.",
}


def get_order_status(session: Session, order_id: str) -> dict:
    order = session.get(Order, order_id)
    if order is None:
        raise CheckoutError("ORDER_NOT_FOUND", f"No order with id {order_id!r}")

    outcome = None
    if order.status != OrderStatus.COMPLETED:
        outcome = _sync_with_paypal(session, order)
        session.refresh(order)

    product = session.get(Product, order.product_id)
    if outcome == Outcome.OUT_OF_STOCK:
        message = "The item sold out before the payment was captured. The buyer was not charged."
    else:
        message = _STATUS_MESSAGES[order.status]
    return {
        "order_id": order.id,
        "status": order.status.value,
        "message": message,
        "product_id": order.product_id,
        "title": product.title if product else None,
        "qty": order.qty,
        "amount": {"value": order.amount, "currency": checkout.CURRENCY},
    }


def _sync_with_paypal(session: Session, order: Order) -> Outcome | None:
    """Fallback capture: normally /paypal/return captures the moment the buyer
    approves. If that redirect never reached us (tab closed, wrong
    APP_BASE_URL), the order sits APPROVED at PayPal. Checking here means an
    agent polling for status still completes the sale. complete_order() is
    idempotent, so racing the return route is safe.
    """
    try:
        pp_status = paypal.get_order(order.paypal_order_id).get("status")
    except paypal.PayPalError:
        return None  # PayPal hiccup: report what we know locally
    if pp_status in ("APPROVED", "COMPLETED"):
        outcome, _ = checkout.complete_order(session, order.paypal_order_id)
        return outcome
    return None
