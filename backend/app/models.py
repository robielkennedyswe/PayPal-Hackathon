"""Database tables: shops, products, orders.

SQLModel classes are both SQLAlchemy tables and pydantic models, so FastAPI
routes and MCP tools can return them directly.

Note: SQLModel skips pydantic validation for table=True models, so input
checks (price format, stock >= 0) belong in the API layer's request models.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _id(prefix: str) -> str:
    # Short, readable, prefixed ids ("prod_3f9a1c2b7d4e") are easier for AI
    # agents to copy between tool calls than integers or full UUIDs, and the
    # prefix makes a wrong id type obvious in logs.
    return f"{prefix}_{secrets.token_hex(6)}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OrderStatus(str, Enum):
    CREATED = "CREATED"      # PayPal order created, waiting on the buyer
    APPROVED = "APPROVED"    # buyer approved in PayPal, not yet captured
    COMPLETED = "COMPLETED"  # captured: money moved, stock decremented


class Shop(SQLModel, table=True):
    __tablename__ = "shops"

    id: str = Field(default_factory=lambda: _id("shop"), primary_key=True)
    slug: str = Field(unique=True, index=True)  # storefront URL: /s/<slug>
    name: str
    paypal_payee_email: str  # seller's sandbox business account; receives payment
    published: bool = False  # only published shops are visible to agents
    # SHA-256 of the seller token (seller_auth.py). None = nobody can manage
    # the shop until a token is issued.
    seller_token_hash: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Product(SQLModel, table=True):
    __tablename__ = "products"

    id: str = Field(default_factory=lambda: _id("prod"), primary_key=True)
    shop_id: str = Field(foreign_key="shops.id", index=True)
    title: str
    description: str
    # JSON columns: SQLite stores them as text, SQLAlchemy (de)serializes.
    attributes: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    price: str  # USD decimal string, e.g. "34.00"; matches PayPal's amount format
    stock: int = 0
    image_path: str | None = None  # where the uploaded photo is stored on disk
    created_at: datetime = Field(default_factory=_now)


class Order(SQLModel, table=True):
    # "order" is a reserved SQL word; a plural table name avoids quoting issues.
    __tablename__ = "orders"

    id: str = Field(default_factory=lambda: _id("ord"), primary_key=True)
    paypal_order_id: str = Field(unique=True, index=True)  # the ?token= on the return URL
    product_id: str = Field(foreign_key="products.id", index=True)
    qty: int = 1
    amount: str  # total charged, USD decimal string
    status: OrderStatus = OrderStatus.CREATED
    paypal_capture_id: str | None = None  # set on capture; useful for the activity feed
    created_at: datetime = Field(default_factory=_now)


class AIUsage(SQLModel, table=True):
    """Claude API spend per UTC day, for the cost limiter (ai_budget.py).

    Persisted (not in memory) so a restart or redeploy can't reset the
    budget mid-day.
    """

    __tablename__ = "ai_usage"

    day: str = Field(primary_key=True)  # "2026-11-10" (UTC)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0  # estimate from token counts x list price


class ListingCache(SQLModel, table=True):
    """Claude vision results keyed by photo hash: the same photo is never
    sent to the API twice (re-uploads, retries, deleting and re-adding)."""

    __tablename__ = "listing_cache"

    image_sha256: str = Field(primary_key=True)
    listing: dict = Field(sa_column=Column(JSON, nullable=False))
    model: str
    created_at: datetime = Field(default_factory=_now)


class Event(SQLModel, table=True):
    """Seller activity feed (screen 3): what AI agents did with a shop.

    Kinds: search (products surfaced in a search), view (get_product),
    checkout (PayPal order created), approved (buyer approved in PayPal),
    sold (captured), cancelled, missed (sold out before capture).
    Integer ids so the dashboard can poll for "events after id N".
    """

    __tablename__ = "events"

    id: int | None = Field(default=None, primary_key=True)
    shop_id: str = Field(foreign_key="shops.id", index=True)
    kind: str
    source: str  # "mcp" (external agent), "agent" (built-in), "web" (PayPal redirects, REST)
    product_id: str | None = None
    order_id: str | None = Field(default=None, index=True)
    detail: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=_now)
