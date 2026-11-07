"""ShopMCP API.

Run from backend/:
    .venv/bin/uvicorn app.main:app --reload --port 8000
Interactive docs: http://localhost:8000/docs
"""

from __future__ import annotations

import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from app import ai_provider, catalog_ai
from app.checkout import Outcome, complete_order
from app.db import UPLOAD_DIR, get_session, init_db
from app.models import Order, Product, Shop
from app.schemas import OrderOut, ProductOut, ProductUpdate, ShopCreate, ShopOut

FRONTEND_URL = (os.getenv("FRONTEND_URL") or "http://localhost:5173").rstrip("/")
# Claude's API rejects images over 5 MB, so we enforce the same cap at upload
# time rather than failing later. (VERIFY the current limit in Anthropic docs.)
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
DEFAULT_STOCK = 1  # new drafts start with 1; seller edits on the review screen


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
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
    shop_id: str, file: UploadFile, session: Session = Depends(get_session)
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
        listing = catalog_ai.generate_listing(dest)
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
    return _to_frontend("cancelled", order)


def _to_frontend(status: str, order: Order | None) -> RedirectResponse:
    # 303 so the browser does a plain GET of the frontend page.
    query = f"status={status}" + (f"&order={order.id}" if order else "")
    return RedirectResponse(f"{FRONTEND_URL}/checkout/result?{query}", status_code=303)
