"""API request/response models.

Table models (models.py) skip validation, so every write goes through one of
these first. Responses are separate "Out" models so we control exactly what
leaves the server (e.g. image_url instead of a filesystem path).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

from app.models import Order, OrderStatus, Product, Shop

PRICE_PATTERN = r"^\d{1,6}\.\d{2}$"  # "34.00": same format catalog_ai and PayPal use
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"  # loose check; PayPal is the real judge


def normalize_price(value: object) -> object:
    """Accept friendly inputs ("20", "20.5", "$1,200") and return "20.00" form.

    Anything unrecognizable is returned unchanged so PRICE_PATTERN rejects it
    with a normal validation error.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return value
    s = str(value).strip().removeprefix("$").replace(",", "").strip()
    m = re.fullmatch(r"(\d{1,6})(?:\.(\d{0,2}))?", s)
    if not m:
        return value
    # String math, not float: float("0.1") etc. would introduce rounding.
    return f"{int(m[1])}.{(m[2] or '').ljust(2, '0')}"


def _utc(dt: datetime) -> datetime:
    # SQLite drops tzinfo on the way back out; everything we store is UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---- requests ----

class ShopCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    paypal_payee_email: str = Field(pattern=EMAIL_PATTERN, max_length=254)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name cannot be blank")
        return v.strip()


class ProductUpdate(BaseModel):
    """PATCH body: only the fields sent are changed."""

    title: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, min_length=10, max_length=2000)
    price: str | None = Field(default=None, pattern=PRICE_PATTERN)
    stock: int | None = Field(default=None, ge=0, le=100_000)
    tags: list[str] | None = Field(default=None, max_length=15)
    attributes: dict[str, str | int | float | bool] | None = None

    @field_validator("price", mode="before")
    @classmethod
    def _normalize_price(cls, v: object) -> object:
        return normalize_price(v) if v is not None else v

    @field_validator("price")
    @classmethod
    def _positive_price(cls, v: str | None) -> str | None:
        if v is not None and float(v) <= 0:
            raise ValueError("price must be greater than 0")  # PayPal rejects 0.00 orders
        return v


class CheckoutCreate(BaseModel):
    product_id: str
    # Range is enforced in checkout.create_checkout so MCP tools get the same rule.
    qty: int = 1


class AgentChat(BaseModel):
    # History is the Anthropic-format message list the previous response
    # returned. It comes from the browser, so it's bounded; tool calls
    # re-validate everything server-side regardless of what it contains.
    history: list[dict] = Field(default_factory=list, max_length=100)  # = agent.MAX_HISTORY_MESSAGES
    message: str = Field(min_length=1, max_length=1000)


# ---- responses ----

class ProductOut(BaseModel):
    id: str
    shop_id: str
    title: str
    description: str
    attributes: dict
    tags: list[str]
    price: str
    stock: int
    image_url: str | None
    created_at: datetime

    @classmethod
    def of(cls, p: Product) -> "ProductOut":
        return cls(
            **p.model_dump(exclude={"image_path", "created_at"}),
            # Only the filename is public; files are served from /uploads.
            image_url=f"/uploads/{p.image_path}" if p.image_path else None,
            created_at=_utc(p.created_at),
        )


class ShopOut(BaseModel):
    id: str
    slug: str
    name: str
    paypal_payee_email: str
    published: bool
    created_at: datetime
    products: list[ProductOut]

    @classmethod
    def of(cls, s: Shop, products: list[Product]) -> "ShopOut":
        return cls(
            **s.model_dump(exclude={"created_at"}),
            created_at=_utc(s.created_at),
            products=[ProductOut.of(p) for p in products],
        )


class StorefrontOut(BaseModel):
    """Public view of a published shop: no seller email, no internal ids."""

    name: str
    slug: str
    products: list[ProductOut]

    @classmethod
    def of(cls, s: Shop, products: list[Product]) -> "StorefrontOut":
        return cls(name=s.name, slug=s.slug, products=[ProductOut.of(p) for p in products])


class OrderOut(BaseModel):
    id: str
    paypal_order_id: str
    product_id: str
    qty: int
    amount: str
    status: OrderStatus
    paypal_capture_id: str | None
    created_at: datetime

    @classmethod
    def of(cls, o: Order) -> "OrderOut":
        return cls(**o.model_dump(exclude={"created_at"}), created_at=_utc(o.created_at))
