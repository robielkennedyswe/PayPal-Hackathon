# ShopMCP

**Make any tiny shop buyable by AI agents.**

A small seller drops in product photos, AI turns each photo into a structured listing, and the seller reviews and publishes. Each published shop gets a public storefront and an **MCP endpoint**, so any MCP-compatible AI agent can search the shop and buy from it. Checkout uses **PayPal Orders v2**, and the buyer approves every payment in PayPal. The agent can never pay on its own.

Built for the *Build What's Next with PayPal and AI* hackathon. All payments run against the **PayPal sandbox**. No real money moves.

> **Status: in development (deadline Nov 12, 2026).** The seller flow and storefront work end to end with a mock AI provider. The MCP server, shopper agent, seller dashboard, real Claude API and hosting are in progress. See [Roadmap](#roadmap).

## Who it's for

Crafters, market vendors and other solo sellers who are too small for PayPal's own agent-ready and store-sync programs, but still want AI shoppers to find and buy their products.

## How it works

```
Seller                        ShopMCP                                   PayPal (sandbox)
──────                        ───────                                   ────────────────
drops photos ───────────────▶ AI vision → draft listing
reviews price/stock, publishes ▶ storefront /s/<slug> + MCP endpoint

AI agent (any MCP client) ──▶ search_products / get_product
                             create_checkout ─────────────────────────▶ create order (seller is payee)
buyer ◀──────────── approve link ◀───────────────────────────────────── approval URL
buyer approves in PayPal ──────────────────────────────────────────────▶
                             /paypal/return ◀───────────────────────── redirect
                             capture + decrement stock ───────────────▶ capture → COMPLETED
```

## What works today

| Feature | Where |
|---|---|
| Add products: shop details, photo drop zone, AI-drafted listing cards | `/sell` |
| Review & publish: inline edits, live "What AI agents will see" JSON, publish | `/sell/<shopId>/review` |
| Public storefront: live prices and stock, sold-out badges | `/s/<slug>` |
| Server-side checkout completion: capture on PayPal return, idempotent, never captures when out of stock | `GET /paypal/return` |
| Checkout result page for the buyer | `/checkout/result` |
| PayPal sandbox order → approve → capture (verified live) | `scripts/paypal_smoke_test.py` |

## Tech stack

- **Frontend:** React 19 + Vite + TypeScript (`frontend/`)
- **Backend:** Python, FastAPI, SQLModel on SQLite (`backend/`)
- **Payments:** PayPal Orders v2 REST (sandbox), OAuth2 client credentials
- **AI:** Claude API (vision for listings, tool use for the shopper agent) behind a provider switch; a mock provider is used during development
- **Agents:** MCP server (FastMCP, streamable HTTP) mounted in the backend *(in progress)*

## Quick start

**Prerequisites:** Python 3.11+, Node.js 20.19+ or 22.12+ (tested with Python 3.13 and Node 24), and a PayPal developer account with sandbox credentials.

```bash
git clone https://github.com/robielkennedyswe/PayPal-Hackathon.git
cd PayPal-Hackathon

# 1. Environment
cp .env.example .env        # then fill in Client_ID and Secret_Key (see below)

# 2. Backend (terminal 1)
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload --port 8000 --timeout-graceful-shutdown 3

# 3. Frontend (terminal 2)
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** and click **Start selling**. API docs are at **http://localhost:8000/docs**.

In mock mode the AI picks a canned listing from words in the photo's **filename**, so name test photos like `blue_mug.jpg`, `white_vase.png` or `sage_bowl.jpg`. Other names get a generic draft.

## Environment variables

Set these in `.env` at the repo root. Write them as `KEY=value` with **no space after `=`**. Blank values fall back to the defaults shown.

| Variable | Default | Purpose |
|---|---|---|
| `Client_ID` | *(required)* | PayPal sandbox app client ID |
| `Secret_Key` | *(required)* | PayPal sandbox app secret |
| `PAYPAL_BASE_URL` | `https://api-m.sandbox.paypal.com` | PayPal API base. Non-sandbox URLs are refused. |
| `AI_PROVIDER` | `mock` | `mock` or `anthropic` |
| `AI_MODEL` | | Claude model id (required when `AI_PROVIDER=anthropic`) |
| `ANTHROPIC_API_KEY` | | Claude API key (required when `AI_PROVIDER=anthropic`) |
| `APP_BASE_URL` | `http://localhost:8000` | Backend URL, used for PayPal return/cancel redirects |
| `FRONTEND_URL` | `http://localhost:5173` | Frontend URL, used for CORS and post-checkout redirects |
| `DATA_DIR` | `backend/data` | SQLite database and uploaded photos |

Get sandbox credentials at [developer.paypal.com](https://developer.paypal.com) → **Apps & Credentials** (Sandbox) → your app.

## Testing a payment as a sandbox buyer

1. At [developer.paypal.com/dashboard/accounts](https://developer.paypal.com/dashboard/accounts), find the **Personal** sandbox account, then **⋯ → View/edit account** and copy its email and password.
2. Run `backend/.venv/bin/python scripts/paypal_smoke_test.py`. It creates a $34.00 order and prints an approve link.
3. Open the link in a **private/incognito window**. If you're logged into the PayPal developer dashboard in the same browser, the checkout page often fails to load.
4. Log in as the **Personal** account and approve. The script captures the payment and prints the capture ID.

## Tests

```bash
cd backend && .venv/bin/python -m pytest          # 16 API tests; PayPal is faked, no network
cd frontend && npm run build && npm run lint      # type-check, build, lint
```

## Project structure

```
backend/     FastAPI app, PayPal client, AI provider, SQLite models, tests  → backend/README.md
frontend/    React + Vite app (seller screens, storefront)                  → frontend/README.md
scripts/     paypal_smoke_test.py, vision_smoke_test.py
.env.example every environment variable (blank values)
```

## Roadmap

- [x] PayPal sandbox client + smoke test
- [x] Mock AI catalog behind a provider switch
- [x] Database, API and tests
- [x] Seller screens: add products, review & publish
- [x] Public storefront
- [ ] `create_checkout` with the seller as PayPal payee, plus a live end-to-end capture test
- [ ] MCP server with `search_products`, `get_product`, `create_checkout`, `get_order_status`
- [ ] Claude vision for listings; Claude tool-use shopper agent
- [ ] Seller dashboard with a live activity feed; built-in shopper agent chat
- [ ] Hosted demo on Render

## AI tools used

- **Claude Code** (Anthropic): used as a coding assistant throughout development, for code, tests, debugging and these docs. All changes were reviewed and committed by the author.
- **Claude API** *(being integrated)*: vision turns product photos into listings; tool use powers the built-in shopper agent.
- **Claude Design:** used to design the app screens.

## License

[MIT](LICENSE) © 2026 Robiel Kennedy
