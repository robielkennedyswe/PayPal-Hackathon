"""Order completion: the server-side half of checkout.

PayPal redirects the buyer to /paypal/return after they approve. That route
calls complete_order(), which captures the payment and decrements stock.
(Monday: create_checkout() lands here too, shared by the MCP tool and the
built-in agent.)

Safety properties:
- Never captures if stock can't cover the order (buyer isn't charged).
- Idempotent: a refreshed return page or a double redirect can't capture
  twice or decrement stock twice.
"""

from __future__ import annotations

from enum import Enum

from sqlalchemy import update
from sqlmodel import Session, select

from app import paypal
from app.models import Order, OrderStatus, Product


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
    if product is None or product.stock < order.qty:
        # Approved but not captured, so no money moves. The authorization
        # simply expires on PayPal's side.
        return Outcome.OUT_OF_STOCK, order

    order.status = OrderStatus.APPROVED
    session.commit()

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
