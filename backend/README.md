# ShopMCP backend

One FastAPI service: the REST API for the seller app and storefront, PayPal sandbox checkout, Claude listings and the shopper agent, the MCP server at `/mcp`, and (in Docker) the built frontend. The [root README](../README.md) covers setup, environment variables and the overall design.

## Setup and run

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # requirements.txt + pytest
.venv/bin/uvicorn app.main:app --reload --port 8000 --timeout-graceful-shutdown 3
```

Configuration is read from `../.env` (repo root). API docs: http://localhost:8000/docs.

Keep `--timeout-graceful-shutdown`: a connected MCP client (e.g. Claude Code) holds a stream open, and without a timeout `--reload` waits for it forever.

## API

🔒 = seller route: needs the shop's token in `X-Seller-Token` (401 without one, 403 if it's wrong; see `app/seller_auth.py`).

| Method & path | Purpose |
|---|---|
| `GET /api/health` | Liveness + active AI provider |
| `POST /api/shops` | Create a shop `{name, paypal_payee_email}`. The response includes `seller_token`, **only this once** |
| 🔒 `GET /api/shops/{shop_id}` | Shop with all its products, including drafts and the payee email |
| 🔒 `POST /api/shops/{shop_id}/products` | Upload **one** photo (multipart `file`) → saved + AI-drafted product |
| 🔒 `PATCH /api/products/{product_id}` | Edit title, description, price, stock, tags, attributes |
| 🔒 `DELETE /api/products/{product_id}` | Delete a product (409 if it has orders) |
| 🔒 `POST /api/shops/{shop_id}/publish` | Publish (needs ≥ 1 product) |
| 🔒 `GET /api/shops/{shop_id}/dashboard?after=N` | Stats, inventory and activity events newer than `N` (polled every 3 s) |
| `GET /api/storefronts` | Directory of published shops |
| `GET /api/storefront/{slug}` | Public view of a published shop (no seller email); 404 otherwise |
| `POST /api/checkout` | `{product_id, qty}` → PayPal order + `approve_url` (same function as the MCP tool) |
| `POST /api/agent/chat` | Built-in shopper agent: `{history, message}` → reply, tool calls, cards |
| `GET /api/ai/usage` | Estimated Claude spend and the active limits |
| `GET /api/orders/{order_id}` | Order status |
| `GET /paypal/return?token=…` | PayPal redirect after approval: capture, then redirect to `/checkout/result` |
| `GET /paypal/cancel?token=…` | PayPal redirect on cancel |
| `POST /mcp` | MCP server (streamable HTTP, stateless): `search_products`, `get_product`, `create_checkout`, `get_order_status` |
| `/uploads/…` | Uploaded product photos (static) |

**Validation** (`app/schemas.py`): prices are USD decimal strings, normalized from friendly input (`"100"` → `"100.00"`, `"$1,200"` → `"1200.00"`) and must be above 0. Stock is 0 or more. Uploads are JPG, PNG, WebP or GIF, up to 5 MB. Checkout quantity is 1–10.

## Modules (`app/`)

| File | Responsibility |
|---|---|
| `main.py` | Routes, seller-token checks, CORS, static uploads, serves the built frontend (`FRONTEND_DIST`), mounts MCP |
| `config.py` | `APP_BASE_URL` / `FRONTEND_URL` (default to Render's `RENDER_EXTERNAL_URL`) |
| `schemas.py` | Request validation and response shapes |
| `models.py` | SQLModel tables: shops, products, orders, ai_usage, listing_cache, events |
| `db.py` | SQLite engine (foreign keys + WAL), `init_db()` incl. adding new columns to old databases |
| `seller_auth.py` | Seller tokens (hash, check, seller link); `python -m app.seller_auth <shop_id>` issues a new one |
| `paypal.py` | Orders v2 client: cached OAuth token, `create_order`, `get_order`, `capture_order`; sandbox-only guard |
| `checkout.py` | `create_checkout()` and `complete_order()`: stock checks, capture, idempotency, `ORDER_ALREADY_CAPTURED` |
| `tools.py` | The 4 tool functions shared by MCP and the built-in agent |
| `mcp_server.py` | MCP server: tool definitions, payment-safety instructions, Host-header allowlist |
| `ai_provider.py` | `mock` vs `anthropic`; `create_message()` is the single path for every Claude call |
| `ai_budget.py` | Daily/total USD budgets, daily call cap, per-visitor hourly limit |
| `catalog_ai.py` | Photo → listing JSON (Claude vision with a strict schema; mock fixtures; SHA-256 cache) |
| `agent.py` | Shopper agent: Claude tool use (max 6 rounds), or a scripted agent in mock mode that still calls the real tools |
| `activity.py` | Dashboard events (search, view, checkout, approved, sold, cancelled), credited to MCP or the built-in agent |

## Data

Everything persistent lives in `DATA_DIR` (default `backend/data/`, gitignored; `/var/data` on Render's disk):

```
shopmcp.db            SQLite database
uploads/<shop_id>/    product photos
```

Delete the folder locally for a fresh start; tables are recreated on startup.

## Tests

```bash
.venv/bin/python -m pytest      # 73 tests
```

They run on a throwaway data dir with `AI_PROVIDER=mock`. PayPal and Claude are faked, and any unexpected real call fails the test. Files: `test_api.py` (shops, validation, checkout outcomes), `test_mcp.py`, `test_agent.py`, `test_claude.py` (Claude path, budgets, cache), `test_dashboard.py`, `test_seller_auth.py`, `test_deploy.py`.

## Smoke scripts (repo root)

```bash
backend/.venv/bin/python scripts/paypal_smoke_test.py   # live sandbox: create a $34 order → approve → capture
backend/.venv/bin/python scripts/vision_smoke_test.py   # photo(s) → listing JSON (mock mode works without a key)
```
