# ShopMCP backend

FastAPI service: REST API for the seller app and storefront, PayPal sandbox checkout, the AI listing generator, and (in progress) the MCP server for AI agents.

## Setup

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # requirements.txt + pytest
```

Configuration is read from `../.env` (repo root). See the [root README](../README.md#environment-variables) for every variable.

Activate the virtual environment with `source .venv/bin/activate` (and `deactivate` to leave), or call `.venv/bin/python` directly.

## Run

```bash
.venv/bin/uvicorn app.main:app --reload --port 8000
```

- Interactive API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/health → `{"ok": true, "ai_provider": "mock"}`

## API

| Method & path | Purpose |
|---|---|
| `GET /api/health` | Liveness + active AI provider |
| `POST /api/shops` | Create a shop `{name, paypal_payee_email}`; returns a unique slug |
| `GET /api/shops/{shop_id}` | Shop with all its products (seller view) |
| `POST /api/shops/{shop_id}/products` | Upload **one** photo (multipart `file`) → saved + AI-drafted product |
| `PATCH /api/products/{product_id}` | Edit title, description, price, stock, tags, attributes |
| `DELETE /api/products/{product_id}` | Delete a product (409 if it has orders) |
| `POST /api/shops/{shop_id}/publish` | Publish (needs ≥ 1 product) |
| `GET /api/storefront/{slug}` | Public view of a **published** shop (no seller email); 404 otherwise |
| `GET /api/orders/{order_id}` | Order status |
| `GET /paypal/return?token=…` | PayPal redirect after approval: capture, then redirect to the frontend |
| `GET /paypal/cancel?token=…` | PayPal redirect on cancel: redirect to the frontend |
| `/uploads/…` | Uploaded product photos (static) |

**Validation rules** (`app/schemas.py`):
- **Prices** are USD decimal strings. Friendly input is normalized (`"100"` → `"100.00"`, `"$1,200"` → `"1200.00"`) and must be greater than 0, since PayPal rejects zero-amount orders.
- **Stock** must be 0 or more.
- **Uploads** must be JPG, PNG, WebP or GIF, up to 5 MB each.

**After PayPal approval:** `/paypal/return` sends the buyer to `FRONTEND_URL/checkout/result?status=<completed|out_of_stock|failed|not_found|cancelled>&order=<id>`.

## Modules (`app/`)

| File | Responsibility |
|---|---|
| `main.py` | FastAPI app, routes, CORS, static uploads, startup DB init |
| `schemas.py` | Request validation and response shapes (`ProductOut`, `ShopOut`, `StorefrontOut`, `OrderOut`) |
| `models.py` | SQLModel tables: `Shop`, `Product`, `Order` (prefixed string ids like `prod_3f9a…`) |
| `db.py` | SQLite engine (foreign keys + WAL on), `init_db()`, per-request session; paths from `DATA_DIR` |
| `paypal.py` | Orders v2 client: cached OAuth token, `create_order`, `get_order`, `capture_order`; sandbox-only guard |
| `checkout.py` | `complete_order()`: capture on return; idempotent, never captures when out of stock, handles `ORDER_ALREADY_CAPTURED` |
| `ai_provider.py` | Reads `AI_PROVIDER` / `AI_MODEL`; one switch between `mock` and `anthropic` |
| `catalog_ai.py` | `generate_listing(image_path)` → strict `Listing` JSON; mock uses `fixtures/listings.json` |

**Mock AI:** listings are chosen by keyword in the photo's filename (`mug`, `vase`, `bowl`, else generic). The Claude vision path (`_claude_listing`) is a TODO; set `AI_PROVIDER=anthropic` once it's implemented.

## Data

Everything persistent lives in `DATA_DIR` (default `backend/data/`, gitignored):

```
data/
  shopmcp.db            SQLite database
  uploads/<shop_id>/    product photos
```

Delete the folder for a fresh start; tables are recreated on startup. In production, point `DATA_DIR` at a persistent disk.

## Tests

```bash
.venv/bin/python -m pytest
```

There are 16 tests in `tests/test_api.py`:
- **Isolation:** they run on a throwaway data dir with `AI_PROVIDER=mock`.
- **No network:** any un-faked PayPal call fails the test.
- **Coverage:** validation, upload limits and path safety, price normalization, publish rules, storefront privacy, and every checkout outcome (completed, refresh idempotency, out of stock, already captured, PayPal errors).

## Smoke scripts (repo root)

```bash
backend/.venv/bin/python scripts/paypal_smoke_test.py   # live sandbox: create $34 order → approve → capture
backend/.venv/bin/python scripts/vision_smoke_test.py   # photo(s) → listing JSON (mock mode works without a key)
```

See the [root README](../README.md#testing-a-payment-as-a-sandbox-buyer) for how to approve as the sandbox buyer.
