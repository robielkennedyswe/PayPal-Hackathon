"""ShopMCP API.

Run from backend/:
    .venv/bin/uvicorn app.main:app --reload --port 8000
Interactive docs: http://localhost:8000/docs
"""

from __future__ import annotations

import os
import re
import secrets
from decimal import Decimal
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from app import activity, agent, ai_budget, ai_provider, catalog_ai, mcp_server
from app.checkout import CheckoutError, Outcome, complete_order, create_checkout
from app.db import UPLOAD_DIR, get_session, init_db
from app.models import Event, Order, OrderStatus, Product, Shop
from app.schemas import AgentChat, CheckoutCreate, DashboardOut, EventOut, OrderOut, ShopCard, ProductOut, ProductUpdate, ShopCreate, ShopOut, StorefrontOut

FRONTEND_URL = (os.getenv("FRONTEND_URL") or "http://localhost:5173").rstrip("/")
# Claude's API rejects images over 5 MB, so we enforce the same cap at upload
# time rather than failing later. (VERIFY the current limit in Anthropic docs.)
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
DEFAULT_STOCK = 1  # new drafts start with 1; seller edits on the review screen


class _MCPMount:
    """ASGI shim in front of the MCP app. The real app is (re)built in
    lifespan because the SDK's session manager can only start once."""

    app = None

    async def __call__(self, scope, receive, send):
        if self.app is None:
            raise RuntimeError("MCP app not started (lifespan did not run)")
        await self.app(scope, receive, send)


_mcp_mount = _MCPMount()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    _mcp_mount.app = mcp_server.build_http_app()
    async with mcp_server.mcp.session_manager.run():
        yield


app = FastAPI(title="ShopMCP", lifespan=lifespan)

# Dev uses the Vite proxy (same origin), so CORS only matters once the
# frontend is hosted on a different domain (Render static site).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# ---------- helpers ----------

def _client_key(request: Request) -> str | None:
    """Who to rate-limit. Behind Render's proxy this is only the visitor's IP
    if uvicorn runs with --proxy-headers (VERIFY on deploy)."""
    return request.client.host if request.client else None


def _shop_or_404(session: Session, shop_id: str) -> Shop:
    shop = session.get(Shop, shop_id)
    if shop is None:
        raise HTTPException(404, "Shop not found")
    return shop


def _product_or_404(session: Session, product_id: str) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Product not found")
    return product


def _products(session: Session, shop_id: str) -> list[Product]:
    return list(
        session.exec(select(Product).where(Product.shop_id == shop_id).order_by(Product.created_at))
    )


def _unique_slug(session: Session, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "shop"
    slug, n = base, 2
    while session.exec(select(Shop).where(Shop.slug == slug)).first():
        slug, n = f"{base}-{n}", n + 1
    return slug


def _safe_filename(name: str) -> str:
    # Keep the original name's words (mock mode picks a fixture by keyword,
    # e.g. "blue_mug.jpg"), drop anything path-like, and add a random prefix
    # so two uploads of "IMG_0001.jpg" never collide.
    path = Path(name or "photo")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem)[:60] or "photo"
    return f"{secrets.token_hex(4)}_{stem}{path.suffix.lower()}"


# ---------- API ----------

@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "ai_provider": ai_provider.provider()}


@app.post("/api/shops", status_code=201)
def create_shop(body: ShopCreate, session: Session = Depends(get_session)) -> ShopOut:
    shop = Shop(
        slug=_unique_slug(session, body.name),
        name=body.name,
        paypal_payee_email=body.paypal_payee_email,
    )
    session.add(shop)
    session.commit()
    session.refresh(shop)
    return ShopOut.of(shop, [])


@app.get("/api/shops/{shop_id}")
def get_shop(shop_id: str, session: Session = Depends(get_session)) -> ShopOut:
    shop = _shop_or_404(session, shop_id)
    return ShopOut.of(shop, _products(session, shop_id))


@app.post("/api/shops/{shop_id}/products", status_code=201)
async def upload_product_photo(
    shop_id: str, file: UploadFile, request: Request, session: Session = Depends(get_session)
) -> ProductOut:
    """One photo in, one AI-drafted product out. The frontend calls this once
    per photo, so each draft card can appear as soon as it's ready."""
    _shop_or_404(session, shop_id)

    filename = _safe_filename(file.filename or "")
    if Path(filename).suffix not in catalog_ai.SUPPORTED_EXTS:
        raise HTTPException(400, f"Unsupported image type; use {sorted(catalog_ai.SUPPORTED_EXTS)}")

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image too large (max 5 MB)")
    if not data:
        raise HTTPException(400, "Empty file")

    rel_path = Path(shop_id) / filename  # stored relative to UPLOAD_DIR
    dest = UPLOAD_DIR / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

    try:
        # Sync SDK call: run it off the event loop so other requests aren't blocked.
        listing = await run_in_threadpool(catalog_ai.generate_listing, dest, client_key=_client_key(request))
    except ai_budget.AIBudgetExceeded as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(429, e.message) from e
    except Exception as e:  # AI or validation failure: don't leave an orphan file
        dest.unlink(missing_ok=True)
        raise HTTPException(502, f"Could not generate listing: {e}") from e

    product = Product(
        shop_id=shop_id,
        title=listing["title"],
        description=listing["description"],
        attributes=listing["attributes"],
        tags=listing["tags"],
        price=listing["suggested_price"],
        stock=DEFAULT_STOCK,
        image_path=rel_path.as_posix(),
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    return ProductOut.of(product)


@app.patch("/api/products/{product_id}")
def update_product(
    product_id: str, body: ProductUpdate, session: Session = Depends(get_session)
) -> ProductOut:
    product = _product_or_404(session, product_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(422, f"{field} cannot be null")
        setattr(product, field, value)
    session.add(product)
    session.commit()
    session.refresh(product)
    return ProductOut.of(product)


@app.delete("/api/products/{product_id}", status_code=204)
def delete_product(product_id: str, session: Session = Depends(get_session)) -> None:
    product = _product_or_404(session, product_id)
    if session.exec(select(Order).where(Order.product_id == product_id)).first():
        # Keep order history intact; the seller can set stock to 0 instead.
        raise HTTPException(409, "Product has orders; set stock to 0 instead")
    if product.image_path:
        (UPLOAD_DIR / product.image_path).unlink(missing_ok=True)
    session.delete(product)
    session.commit()


@app.post("/api/shops/{shop_id}/publish")
def publish_shop(shop_id: str, session: Session = Depends(get_session)) -> ShopOut:
    shop = _shop_or_404(session, shop_id)
    if not _products(session, shop_id):
        raise HTTPException(400, "Add at least one product before publishing")
    shop.published = True
    session.add(shop)
    session.commit()
    session.refresh(shop)
    # Re-query after commit: commit expires loaded objects, and pydantic's
    # model_dump reads expired SQLModel instances as empty, not reloaded.
    return ShopOut.of(shop, _products(session, shop_id))


FEED_LIMIT = 50


@app.get("/api/shops/{shop_id}/dashboard")
def dashboard(shop_id: str, after: int = 0, session: Session = Depends(get_session)) -> DashboardOut:
    """Seller dashboard (screen 3), polled every few seconds.

    after=<last event id seen> returns only newer events, so polling stays
    cheap; stats and inventory are always current.
    """
    shop = _shop_or_404(session, shop_id)
    products = _products(session, shop_id)
    titles = {p.id: p.title for p in products}
    product_ids = list(titles)

    orders = list(session.exec(select(Order).where(Order.product_id.in_(product_ids)))) if product_ids else []
    sold = [o for o in orders if o.status == OrderStatus.COMPLETED]
    units_by_product: dict[str, int] = {}
    for o in sold:
        units_by_product[o.product_id] = units_by_product.get(o.product_id, 0) + o.qty

    def count(kind: str) -> int:
        return len(session.exec(select(Event.id).where(Event.shop_id == shop_id, Event.kind == kind)).all())

    query = select(Event).where(Event.shop_id == shop_id, Event.id > after).order_by(Event.id.desc()).limit(FEED_LIMIT)
    events = list(session.exec(query))

    return DashboardOut(
        shop=ShopOut.of(shop, products),
        mcp_url=f"{mcp_server.public_base_url()}/mcp",
        stats={
            "searches": count("search"),
            "views": count("view"),
            "checkouts": len(orders),
            "sales": len(sold),
            "units_sold": sum(o.qty for o in sold),
            # Decimal sum of decimal strings: no float rounding in money.
            "revenue": str(sum((Decimal(o.amount) for o in sold), Decimal("0.00"))),
        },
        units_sold=units_by_product,
        events=[EventOut.of(e, titles.get(e.product_id or "")) for e in events],
    )


@app.get("/api/storefronts")
def list_storefronts(session: Session = Depends(get_session)) -> list[ShopCard]:
    """Public shop directory: published shops with at least one product,
    newest first."""
    shops = session.exec(select(Shop).where(Shop.published == True).order_by(Shop.created_at.desc())).all()  # noqa: E712
    cards = []
    for shop in shops:
        products = _products(session, shop.id)
        if not products:
            continue
        prices = sorted(Decimal(p.price) for p in products)  # Decimal: "100.00" sorts after "20.00"
        cards.append(ShopCard(
            name=shop.name,
            slug=shop.slug,
            product_count=len(products),
            in_stock_count=sum(1 for p in products if p.stock > 0),
            price_min=str(prices[0]),
            price_max=str(prices[-1]),
            images=[f"/uploads/{p.image_path}" for p in products if p.image_path][:3],
        ))
    return cards


@app.get("/api/storefront/{slug}")
def storefront(slug: str, session: Session = Depends(get_session)) -> StorefrontOut:
    """Public shop page data. Unpublished shops look exactly like missing ones."""
    shop = session.exec(select(Shop).where(Shop.slug == slug)).first()
    if shop is None or not shop.published:
        raise HTTPException(404, "Shop not found")
    return StorefrontOut.of(shop, _products(session, shop.id))


# Map CheckoutError codes to HTTP status. The body keeps the stable code so
# the frontend can branch on it.
_CHECKOUT_HTTP = {
    "INVALID_QUANTITY": 422,
    "PRODUCT_NOT_FOUND": 404,
    "OUT_OF_STOCK": 409,
    "PAYMENT_PROVIDER_ERROR": 502,
}


@app.post("/api/checkout", status_code=201)
def checkout(body: CheckoutCreate, session: Session = Depends(get_session)) -> dict:
    """Create a PayPal order; the buyer opens approve_url to pay.
    Same function the MCP create_checkout tool calls."""
    try:
        return create_checkout(session, body.product_id, body.qty)
    except CheckoutError as e:
        raise HTTPException(_CHECKOUT_HTTP.get(e.code, 400), {"code": e.code, "message": e.message}) from e


@app.post("/api/agent/chat")
def agent_chat(body: AgentChat, request: Request, session: Session = Depends(get_session)) -> dict:
    """One shopper-agent turn (screen 4). Send back the returned history next time."""
    return agent.chat(session, body.history, body.message.strip(), client_key=_client_key(request))


@app.get("/api/ai/usage")
def ai_usage() -> dict:
    """Today's estimated Claude spend vs. the limits (no secrets, no per-visitor data)."""
    return {"provider": ai_provider.provider(), "model": ai_provider.model(), **ai_budget.status()}


@app.get("/api/orders/{order_id}")
def get_order(order_id: str, session: Session = Depends(get_session)) -> OrderOut:
    order = session.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    return OrderOut.of(order)


# ---------- PayPal redirects ----------
# After approving (or cancelling), PayPal sends the buyer's browser here with
# ?token=<paypal order id>. We finish server-side, then bounce to the frontend.

@app.get("/paypal/return")
def paypal_return(token: str, session: Session = Depends(get_session)) -> RedirectResponse:
    outcome, order = complete_order(session, token)
    return _to_frontend(outcome.value, order)


@app.get("/paypal/cancel")
def paypal_cancel(token: str, session: Session = Depends(get_session)) -> RedirectResponse:
    order = session.exec(select(Order).where(Order.paypal_order_id == token)).first()
    if order is not None:
        product = session.get(Product, order.product_id)
        if product is not None:
            activity.record(session, shop_id=product.shop_id, kind="cancelled", product_id=product.id,
                            order_id=order.id, detail={"qty": order.qty, "title": product.title},
                            once=True, event_source=activity.order_source(session, order.id))
        session.refresh(order)
    return _to_frontend("cancelled", order)


def _to_frontend(status: str, order: Order | None) -> RedirectResponse:
    # 303 so the browser does a plain GET of the frontend page.
    query = f"status={status}" + (f"&order={order.id}" if order else "")
    return RedirectResponse(f"{FRONTEND_URL}/checkout/result?{query}", status_code=303)


# ---------- MCP (must be last) ----------
# Mounted at the root with the MCP app's own route at exactly /mcp: mounting
# at "/mcp" instead would make Starlette 307-redirect /mcp -> /mcp/, which
# some MCP clients don't follow on POST. Being last, every route above wins.
app.mount("/", _mcp_mount)
