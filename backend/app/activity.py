"""Records what AI agents do, for the seller dashboard's live activity feed.

The shared tool and checkout functions call record(); they don't know who
called them, so the caller sets `source` once (mcp_server._run -> "mcp",
agent.chat -> "agent"). A ContextVar keeps that per request/thread.

Recording is best-effort: a failure to log activity must never break a
search or a payment, so errors are swallowed (and logged).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar

from sqlmodel import Session, select

from app.models import Event

log = logging.getLogger(__name__)

source: ContextVar[str] = ContextVar("activity_source", default="web")


@contextmanager
def as_source(name: str):
    token = source.set(name)
    try:
        yield
    finally:
        source.reset(token)


def record(session: Session, *, shop_id: str, kind: str, product_id: str | None = None,
           order_id: str | None = None, detail: dict | None = None, once: bool = False,
           event_source: str | None = None) -> None:
    """Add one event and commit. once=True skips it if this order already has
    an event of this kind (e.g. repeated status polls of a sold-out order)."""
    try:
        if once and order_id and session.exec(
            select(Event.id).where(Event.order_id == order_id, Event.kind == kind)
        ).first():
            return
        session.add(Event(shop_id=shop_id, kind=kind, product_id=product_id, order_id=order_id,
                          detail=detail or {}, source=event_source or source.get()))
        session.commit()
    except Exception:  # noqa: BLE001 - activity logging must never break the caller
        log.exception("could not record %s event", kind)
        session.rollback()


def order_source(session: Session, order_id: str) -> str:
    """Who started an order: approvals and sales arrive through PayPal's
    redirect ("web"), but credit belongs to the agent that made the checkout."""
    found = session.exec(
        select(Event.source).where(Event.order_id == order_id, Event.kind == "checkout")
    ).first()
    return found or source.get()
