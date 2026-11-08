# PayPal-Hackathon — ShopMCP

Project submission for the "Build What's Next with PayPal and AI" hackathon (Devpost). Integration is built against PayPal's **sandbox** API (`api-m.sandbox.paypal.com`), not production.

**Deadline: Thu Nov 12, 2026, 3:00 PM EST. Target: submit by noon.**

## Status (as of 2026-11-08, end of Sunday's work)

Saturday + Sunday schedule complete and pushed. Seller flow works end to end in mock AI mode. Monday started early: payee check + `create_checkout` done and **live-verified** (sandbox approve → `/paypal/return` capture → COMPLETED, stock decremented). **Next:** MCP server + 4 tools, mock agent.

Done:
- **Repo:** MIT `LICENSE`, `.env.example`, `.gitignore`. `.env` was never committed.
- **PayPal** (`backend/app/paypal.py`): cached OAuth token, `create_order` / `get_order` / `capture_order`, refuses non-sandbox URLs. `scripts/paypal_smoke_test.py` completed a real $34.00 sandbox capture.
- **AI** (mock only): `ai_provider.py` switch; `catalog_ai.generate_listing()` with the strict `Listing` schema; fixtures in `fixtures/listings.json`. `_claude_listing()` is a TODO for Tuesday.
- **DB** (`db.py`, `models.py`): SQLite, Shop/Product/Order, prefixed string ids (`shop_…`, `prod_…`, `ord_…`), foreign keys + WAL on. Everything persistent lives in `DATA_DIR`.
- **API** (`main.py`, `schemas.py`, `checkout.py`): shops, photo upload → AI draft, product PATCH/DELETE, publish, `GET /api/storefront/{slug}` (published only, no seller email), `GET /api/orders/{id}`, `/paypal/return` + `/paypal/cancel`.
  - `checkout.complete_order()` skips capture when out of stock, is idempotent (atomic conditional update), and handles `ORDER_ALREADY_CAPTURED`.
  - Prices normalize (`"100"` → `"100.00"`) and must be > 0.
  - 21 pytest tests in `backend/tests/` (PayPal is faked; tests never hit the network).
- **Checkout** (`checkout.create_checkout()` + `POST /api/checkout`): qty 1–10, published shops only, stock check, Decimal totals, seller as payee, line item on the PayPal page. Raises `CheckoutError` with stable codes (`INVALID_QUANTITY`, `PRODUCT_NOT_FOUND`, `OUT_OF_STOCK`, `PAYMENT_PROVIDER_ERROR`). MCP `create_checkout` must call this function. 21 tests.
- **Frontend** (`frontend/`, React + Vite + TS):
  - Tiny History-API router (`router.ts` + `components/Link.tsx`) instead of react-router.
  - Routes: `/` home, `/sell` and `/sell/:shopId` (screen 1), `/sell/:shopId/review` (screen 2), `/s/:slug` (public storefront), `/checkout/result`.
  - `agentView.ts` defines the JSON shown in "What AI agents will see". **Monday's MCP `get_product` must return this same shape.**

Not done / unverified:
- Screens 3 (dashboard) and 4 (shopper agent), MCP server, `agent.py`, Claude API, Render deploy.
- Verify in docs: Claude's 5 MB image limit, Render persistent disk for `DATA_DIR`.
- Deployed frontend needs the backend URL (`VITE_API_BASE_URL` or serve the built frontend from FastAPI).

### Running locally
```
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000   # API docs: :8000/docs
cd frontend && npm run dev                                          # http://localhost:5173 (proxies /api /mcp /paypal /uploads)
cd backend && .venv/bin/python -m pytest                            # tests (requirements-dev.txt)
backend/.venv/bin/python scripts/paypal_smoke_test.py               # live sandbox order -> approve -> capture
backend/.venv/bin/python scripts/vision_smoke_test.py               # mock listing JSON
```
Delete `backend/data/` for a clean database (it has test shops from development).

PayPal OAuth by hand (verified):
```
set -a; source .env; set +a
curl -X POST "https://api-m.sandbox.paypal.com/v1/oauth2/token" \
  -u "$Client_ID:$Secret_Key" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials"
```

### Gotchas hit
- `.env` values must be `KEY=value` with **no space** after `=`. A space breaks `source` in bash/zsh.
- **Sandbox checkout page:** open approve links in a **private/incognito window** and log in with the sandbox **Personal** account (credentials under developer.paypal.com → Sandbox accounts → View/edit). A logged-in developer-dashboard session makes the checkout page error out. Put this in the README.
- **Mock AI picks a fixture from the filename** (`blue_mug.jpg` → mug; also `vase`, `bowl`), not the image. Uploads keep the original name words for this reason.
- **SQLAlchemy expires objects on commit**, and pydantic `model_dump` reads expired SQLModel objects as empty instead of reloading them. Re-query or `refresh()` after `commit()` before building a response.
- **Don't disable a button while a blur-triggered save runs.** Clicking Publish right after editing blurred the field, started a save, disabled the button mid-click, and silently dropped the click. `publish()` saves pending edits itself instead.
- **Commits:** author is `Robiel Kennedy <287809215+robielkennedyswe@users.noreply.github.com>` (repo-local git config). No `Co-Authored-By` trailers, so `robielkennedyswe` stays the only contributor; Claude Code is credited in the README/Devpost instead.
- **PayPal does not validate `payee.email_address` at create time** (verified 2026-11-08: made-up emails are accepted). A typo only fails at approval/capture. Demo shops must use a real sandbox business email; ideally a *second* sandbox business account so payment visibly goes to the seller, not the app's own account (`sb-jptms53373342@business.example.com`). Spec + error names (`PAYEE_ACCOUNT_INVALID`, `ORDER_ALREADY_CAPTURED`) checked in Orders v2 docs.
- With `experience_context`, a new PayPal order's status is `PAYER_ACTION_REQUIRED` (not `CREATED`) and the link is `rel: payer-action`.
- Port 5173 can be taken by another local project. Vite then moves to 5174, which breaks `FRONTEND_URL` redirects.

## What we're building: ShopMCP

ShopMCP makes any tiny shop buyable by AI agents.
- A small seller uploads product photos. AI vision turns each photo into a structured listing (title, description, attributes, tags, suggested price). The seller reviews price/stock and publishes.
- Each published shop gets a storefront page and an **MCP endpoint**, so any MCP-compatible AI agent can search it and buy from it.
- Checkout uses **PayPal Orders v2 (sandbox)** with the seller as payee. The buyer must approve every payment in PayPal; the agent can never pay on its own.
- A built-in "shopper agent" chat page lets judges test without installing an MCP client.

Target user: solo/small sellers (crafters, market vendors) too small for PayPal's own agent-ready / store sync programs.

## Hard rules
- **PayPal sandbox only.** Base URL `https://api-m.sandbox.paypal.com`. Never live endpoints.
- **No secrets in code.** Read everything from environment variables (`.env`, loaded with python-dotenv). Never print or log secrets or tokens. `.env` must stay in `.gitignore`.
- Keep `.env.example` up to date with every variable name (blank values).
- **Mock AI is for development only.** The hosted demo, demo video and anything judges use must run with `AI_PROVIDER=anthropic`. AI is a hard hackathon requirement.
- Prefer a reliable, polished end-to-end demo path over extra features.
- Explain the code you write (short comments on non-obvious parts, plus a summary after each change).
- Flag anything that depends on PayPal / Render / Anthropic API details that should be verified in current docs.
- Small, frequent commits with clear messages (judges look at commit history). Don't push until I've reviewed `git status`.

## Environment variables
Existing names in `.env` are kept as-is (`Client_ID`, `Secret_Key`). Full list:
```
Client_ID=                                   # PayPal sandbox client ID (existing)
Secret_Key=                                  # PayPal sandbox secret (existing)
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
AI_PROVIDER=mock                             # mock now; switch to anthropic by Tuesday
AI_MODEL=                                    # set when switching to the real API
ANTHROPIC_API_KEY=                           # leave blank until Tuesday
APP_BASE_URL=http://localhost:8000           # used for PayPal return/cancel URLs
FRONTEND_URL=http://localhost:5173
DATA_DIR=                                    # optional; default backend/data (SQLite db + uploads; point at a persistent disk on Render)
```
Remember: no space after `=`.

## AI provider (mock now, Claude API later)
All AI calls go through one switch so the rest of the app never changes when we move to the real API.
- `backend/app/ai_provider.py` reads `AI_PROVIDER` (`mock` | `anthropic`, default `mock`) and `AI_MODEL`.
- **Catalog (`catalog_ai.generate_listing(image_path)`)** returns strict JSON: `title`, `description`, `attributes` (object), `tags` (list), `suggested_price` (USD decimal string). The same validation runs in both modes.
  - Mock: return realistic canned listings from `backend/app/fixtures/listings.json`, picked by filename keyword (mug, vase, bowl) with a generic fallback.
  - Anthropic: send the image to Claude vision and request the same JSON schema. Leave as a clear TODO with the signature ready until Tuesday.
- **Built-in shopper agent (`agent.py`)**:
  - Mock: a scripted conversation that still calls the **real** tool functions (real search, real PayPal sandbox order), so the full flow is testable.
  - Anthropic: Claude tool use over the same four tool functions.
- **Testing the agent with real AI before Tuesday:** connect Claude Code (or Claude Desktop) to the local MCP server as the shopper agent, e.g. `claude mcp add --transport http shopmcp http://localhost:8000/mcp` (verify exact syntax in Claude Code docs). This uses the Claude subscription, not API credits.
- When switching on Tuesday: use a smaller model while testing, set a monthly spend limit in the Claude Console, and cache generated listings in the DB so the same photo is never sent twice.

## Stack
- Frontend: React + Vite (TypeScript optional)
- Backend: Python 3.11+, FastAPI, with the MCP server (FastMCP, streamable HTTP) mounted in the same service
- DB: SQLite (via SQLModel or plain sqlite3)
- AI: mock provider now; Claude API (vision for catalog, tool use for the shopper agent) by Tuesday
- Payments: PayPal Orders v2 REST (create, capture, get), reusing the verified OAuth flow above
- Hosting: Render (single web service + static site). Use a paid instance through judging so it doesn't sleep.

## Suggested layout
```
backend/
  requirements.txt
  app/main.py          FastAPI app, routes, mounts MCP
  app/schemas.py       API request/response models (validation lives here)
  app/checkout.py      order capture / completion (shared by routes + MCP tools)
  app/paypal.py        OAuth token caching (~9h expiry), create_order, capture_order, get_order
  app/ai_provider.py   reads AI_PROVIDER / AI_MODEL; mock vs anthropic
  app/catalog_ai.py    photo -> listing JSON (mock fixtures now, Claude vision later)
  app/fixtures/listings.json   canned listings for mock mode
  app/mcp_server.py    MCP tools (see below)
  app/agent.py         built-in shopper agent (scripted in mock mode, Claude tool use later)
  app/db.py, models.py shops, products, orders
frontend/              Vite React app (4 screens below)
scripts/
  paypal_smoke_test.py token -> create order -> print approve link -> capture
  vision_smoke_test.py one photo -> listing JSON (works in mock mode)
LICENSE (MIT), README.md, .env.example
```

## Data model (minimum)
- Shop: id, slug, name, paypal_payee_email
- Product: id, shop_id, title, description, attributes (JSON), tags, price (decimal string, USD), stock, image_path
- Order: id, paypal_order_id, product_id, qty, amount, status (CREATED/APPROVED/COMPLETED), created_at

## MCP tools (same Python functions back the built-in agent)
- `search_products(query: str, max_price: float | None)` -> list of {id, title, price, shop, short description, stock}
- `get_product(product_id: str)` -> full listing
- `create_checkout(product_id: str, qty: int = 1)` -> {order_id, approve_url, amount}. Calls Orders v2 create with intent CAPTURE, `purchase_units[0].payee.email_address` = seller. VERIFY payee-by-email behavior in current Orders v2 docs.
- `get_order_status(order_id: str)` -> status; capture happens server-side on the PayPal return URL.

## PayPal flow
1. Get access token (client credentials, as verified above), cache until expiry.
2. `POST /v2/checkout/orders` -> approve link (`rel: payer-action` or `approve`).
3. Buyer approves on sandbox with the sandbox personal account.
4. PayPal redirects to `APP_BASE_URL/paypal/return?token=<order_id>` -> backend calls `POST /v2/checkout/orders/{id}/capture` -> mark COMPLETED, decrement stock.
5. Frontend shows the sale live on the seller dashboard (polling is fine; webhooks are optional).

## Screens (designed in Claude Design)
1. Add products: shop name, PayPal sandbox business email, photo drop zone; AI draft listing cards appear.
2. Review and publish: editable title/description/price/stock per product; side panel "What AI agents will see" (the listing JSON); Publish button.
3. Seller dashboard: "Live to AI agents" banner with MCP endpoint + Copy; stats; live activity feed (Search -> Checkout -> Approved -> Sold via AI agent); inventory; "connect any AI agent" steps.
4. Shopper agent: chat with tool-call chips, product card, PayPal approval card (use PayPal JS SDK button in the real build), confirmation; side panel tracing each tool call.
Look: warm off-white #FBFAF7, ink #17181C, seller teal #0B6B58, agent indigo #4338CA; Space Grotesk headings, Inter body, JetBrains Mono for code/tool calls.

## Schedule
| Day | Goal |
|---|---|
| Sat ✅ | LICENSE (MIT), `.env.example`, check `.gitignore`; `paypal_smoke_test.py` working (OAuth already verified); AI provider switch + mock catalog; `vision_smoke_test.py` working in mock mode |
| Sun ✅ | Seller onboarding UI + DB + publish (+ public storefront) |
| Mon | MCP server + 4 tools wired to PayPal; test with Claude Code / Claude Desktop as the shopper agent |
| Tue | **Switch to real Claude API** (catalog + built-in agent); shopper agent page, live seller dashboard, deploy to Render |
| Wed | Polish, README (setup + sandbox buyer test login instructions), demo video, Devpost write-up; stretch goal |
| Thu AM | Buffer, submit |

Fallback if MCP slips: the built-in agent calls the tool functions directly via Claude tool use.
Stretch (Wed, only if core is done): shopper "snap to find" — screenshot -> vision -> query -> `search_products`.

## Submission checklist (don't leave for last)
- [ ] Public repo, MIT `LICENSE` in root (shows in GitHub About)
- [ ] README: what it is, setup + run steps, env vars, sandbox test buyer instructions, AI tools used and how
- [ ] Hosted demo URL on Render with `AI_PROVIDER=anthropic`, awake through judging
- [ ] Demo video < 3 min, public on YouTube, no copyrighted music/trademarks, real AI (not mock)
- [ ] Devpost text description + AI tools list
- [ ] Check repo from a logged-out browser; no secrets in git history
