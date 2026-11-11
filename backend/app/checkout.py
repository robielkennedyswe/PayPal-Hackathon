"""Checkout: create a PayPal order, then capture it after the buyer approves.

Both halves are plain functions shared by the HTTP routes, the MCP tools and
the built-in shopper agent, so every entry point follows the same rules.

1. create_checkout() creates a PayPal order with the seller as payee and
   returns the approval link. The agent hands that link to the human; it can
   never approve or pay by itself.
2. PayPal redirects the buyer to /paypal/return after they approve. That
   route calls complete_order(), which captures and decrements stock.

Safety properties:
- Stock is checked at create time (fail fast) AND at capture time, because
  it may sell out while the buyer is on PayPal. Stock is never reserved.
- Never captures if stock can't cover the order (buyer isn't charged).
- Idempotent: a refreshed return page or a double redirect can't capture
  twice or decrement stock twice.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from sqlalchemy import update
from sqlmodel import Session, select

from app import activity, paypal
from app.models import Order, OrderStatus, Product, Shop

MAX_QTY = 10  # per checkout; stops a confused agent from ordering 500 mugs
CURRENCY = "USD"


class CheckoutError(Exception):
    """A checkout the caller should be told about, not a server bug.

    `code` is stable and machine-readable (agents and the frontend branch on
    it); `message` is safe to show to a buyer or an AI agent.
    """

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def create_checkout(session: Session, product_id: str, qty: int = 1) -> dict:
    """Create a PayPal order for `qty` of a product and return its approval link."""
    if not isinstance(qty, int) or isinstance(qty, bool) or not 1 <= qty <= MAX_QTY:
        raise CheckoutError("INVALID_QUANTITY", f"qty must be a whole number from 1 to {MAX_QTY}")

    product = session.get(Product, product_id)
    shop = session.get(Shop, product.shop_id) if product else None
    # Unpublished shops and not-yet-live drafts look missing, same as the storefront.
    if product is None or shop is None or not (shop.published and product.live):
        raise CheckoutError("PRODUCT_NOT_FOUND", f"No product with id {product_id!r}")
    if product.stock < qty:
        raise CheckoutError(
            "OUT_OF_STOCK", f"Only {product.stock} of {product.title!r} in stock"
        )

    # Decimal, not float: 3 * 19.99 must be exactly "59.97".
    amount = str((Decimal(product.price) * qty).quantize(Decimal("0.01")))

    def _create(description: str, item_name: str) -> dict:
        return paypal.create_order(
            amount,
            CURRENCY,
            description=description,
            payee_email=shop.paypal_payee_email,
            item={"name": item_name, "quantity": qty, "unit_amount": product.price},
        )

    try:
        try:
            pp_order = _create(f"{shop.name}: {product.title}", product.title)
        except paypal.PayPalError as e:
            # PayPal's firewall answers 406 when seller-written text looks like
            # code (e.g. "<script>", "javascript:", "onerror="; verified in
            # sandbox). Retry once with neutral text so the sale still works;
            # the buyer still sees the right amount and quantity.
            if e.status != 406:
                raise
            pp_order = _create("Order from ShopMCP", f"ShopMCP item {product.id}")
    except paypal.PayPalError as e:
        raise CheckoutError("PAYMENT_PROVIDER_ERROR", "PayPal could not create the order") from e

    approve_url = paypal.approve_url(pp_order)
    if not approve_url:  # shouldn't happen, but never hand an agent a broken link
        raise CheckoutError("PAYMENT_PROVIDER_ERROR", "PayPal returned no approval link")

    order = Order(paypal_order_id=pp_order["id"], product_id=product.id, qty=qty, amount=amount)
    session.add(order)
    session.commit()
    session.refresh(order)

    result = {
        "order_id": order.id,  # our id; pass to get_order_status
        "approve_url": approve_url,
        "amount": amount,
        "currency": CURRENCY,
        "product_id": product.id,
        "title": product.title,
        "qty": qty,
        "status": order.status.value,
        "next_step": "Send approve_url to the buyer. They approve the payment in PayPal; "
                     "the agent cannot pay on their behalf.",
        # Sandbox only (hard rule), so tell the agent how a tester approves.
        # A logged-in PayPal developer session breaks the sandbox checkout page.
        "sandbox_note": "PayPal sandbox (test) payment: open approve_url in a private/incognito "
                        "window and log in with a PayPal sandbox Personal account.",
    }
    # Built before recording: record() commits, which expires loaded objects.
    activity.record(session, shop_id=shop.id, kind="checkout", product_id=product.id,
                    order_id=result["order_id"], detail={"qty": qty, "amount": amount, "title": product.title})
    return result


class Outcome(str, Enum):
    COMPLETED = "completed"
    OUT_OF_STOCK = "out_of_stock"
    NOT_FOUND = "not_found"
    FAILED = "failed"


def complete_order(session: Session, paypal_order_id: str) -> tuple[Outcome, Order | None]:
    order = session.exec(select(Order).where(Order.paypal_order_id == paypal_order_id)).first()
    if order is None:
        return Outcome.NOT_FOUND, None
    if order.status == OrderStatus.COMPLETED:
        return Outcome.COMPLETED, order  # already done (page refresh)

    product = session.get(Product, order.product_id)
    credit = activity.order_source(session, order.id)  # the agent that started this order
    if product is None or product.stock < order.qty:
        # Approved but not captured, so no money moves. The authorization
        # simply expires on PayPal's side.
        if product is not None:
            activity.record(session, shop_id=product.shop_id, kind="missed", product_id=product.id,
                            order_id=order.id, detail={"qty": order.qty, "title": product.title},
                            once=True, event_source=credit)
        return Outcome.OUT_OF_STOCK, order

    order.status = OrderStatus.APPROVED
    session.commit()
    activity.record(session, shop_id=product.shop_id, kind="approved", product_id=product.id,
                    order_id=order.id, detail={"qty": order.qty, "amount": order.amount, "title": product.title},
                    once=True, event_source=credit)

    try:
        result = paypal.capture_order(paypal_order_id)
    except paypal.PayPalError as e:
        if not _already_captured(e):
            return Outcome.FAILED, order
        # A concurrent request (or earlier attempt) already captured it:
        # read the order back so we still record the capture id.
        result = paypal.get_order(paypal_order_id)

    if result.get("status") != "COMPLETED":
        return Outcome.FAILED, order

    capture_id = _capture_id(result)

    # Atomic "only if not already completed" update. If two requests race
    # past the status check above, exactly one gets rowcount == 1, so stock
    # is decremented exactly once.
    claimed = session.exec(
        update(Order)
        .where(Order.id == order.id, Order.status != OrderStatus.COMPLETED)
        .values(status=OrderStatus.COMPLETED, paypal_capture_id=capture_id)
    ).rowcount
    if claimed == 1:
        session.exec(
            update(Product)
            .where(Product.id == product.id)
            .values(stock=Product.stock - order.qty)
        )
    session.commit()
    if claimed == 1:  # exactly once per order, same guarantee as the stock decrement
        activity.record(session, shop_id=product.shop_id, kind="sold", product_id=product.id,
                        order_id=order.id, detail={"qty": order.qty, "amount": order.amount, "title": product.title},
                        event_source=credit)
    session.refresh(order)
    return Outcome.COMPLETED, order


def _already_captured(e: paypal.PayPalError) -> bool:
    body = e.body if isinstance(e.body, dict) else {}
    return any(d.get("issue") == "ORDER_ALREADY_CAPTURED" for d in body.get("details", []))


def _capture_id(order: dict) -> str | None:
    try:
        return order["purchase_units"][0]["payments"]["captures"][0]["id"]
    except (KeyError, IndexError):
        return None
