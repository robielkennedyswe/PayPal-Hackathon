# ShopMCP frontend

React 19 + Vite + TypeScript: the seller screens, shop directory and storefronts, the built-in shopper agent, and the checkout result page.

## Setup & scripts

Requires Node.js 20.19+ or 22.12+.

```bash
npm install
npm run dev       # http://localhost:5173
npm run build     # type-check + production build into dist/
npm run lint      # oxlint
npm run preview   # serve the production build
```

The backend must be running on `:8000` (see [backend/README.md](../backend/README.md)). In development, Vite proxies `/api`, `/mcp`, `/paypal` and `/uploads` to it (`vite.config.ts`), so the app calls relative URLs and needs no CORS setup. In production (Docker/Render), FastAPI serves `dist/` from the same origin.

## Routes

| Path | Page | What it does |
|---|---|---|
| `/` | `Home` | Landing page |
| `/shops` | `Shops` | Directory of published shops |
| `/s/:slug` | `Storefront` | Public page for a published shop: live prices, stock, sold-out badges |
| `/sell`, `/sell/:shopId` | `AddProducts` (screen 1) | Shop name + PayPal email, photo drop zone (on phones, tapping it offers the camera, photo library or files), AI draft cards. The first upload creates the shop and stores its seller token; the URL gains the shop id so a refresh resumes it. |
| `/sell/:shopId/review` | `Review` (screen 2) | Edit each listing, live "What AI agents will see" JSON. Drafts save when you leave a field; once published, edits and newly added photos go live only on **Save changes** (and leaving with unsaved edits, including the Back button, asks first). |
| `/sell/:shopId/dashboard` | `Dashboard` (screen 3) | MCP endpoint, stats, live activity feed (polled), inventory, "connect any AI agent" steps, Copy seller link |
| `/agent` | `ShopperAgent` (screen 4) | Chat with the built-in agent: tool-call chips, product/approval/confirmation cards, trace panel, Recents |
| `/checkout/result` | `CheckoutResult` | Where buyers land after PayPal (`?status=…&order=…`) |

## Structure

```
src/
  main.tsx            entry; imports a seller link (#seller=…) before the first render
  App.tsx             route table
  router.ts           tiny History-API router: navigate(), useLocation(), matchPath(), setLeaveGuard()
  api.ts              typed fetch wrappers; adds X-Seller-Token on seller routes; FastAPI errors → ApiError
  myShops.ts          shops this browser manages, with their seller tokens (localStorage + in-memory fallback)
  chatStore.ts        shopper-agent conversations for Recents (localStorage)
  useShops.ts         loads the public shop directory
  types.ts            types mirroring backend/app/schemas.py; normalizePrice()
  agentView.ts        listing JSON as AI agents receive it (must match the MCP get_product tool)
  time.ts             "3m ago" formatting
  components/         Link, TopBar (site nav: "Start selling" for visitors, setup + dashboard for sellers; sandbox badge), SetupSteps, ShopGrid
  pages/              one file per route above
  index.css           design tokens + base styles
  app.css             component styles
```

**Why no react-router?** The app has a handful of fixed routes, so a ~50-line router does the job without adding a dependency. Back/forward and refresh work, because URLs are real paths.

## Design

Tokens are CSS variables in `src/index.css`. Components use the variables, never raw hex values.

- **Colors:**
  - warm off-white `--bg` `#FBFAF7` and ink `--ink` `#17181C`
  - **seller teal** `--seller` `#0B6B58`
  - **agent indigo** `--agent` `#4338CA`
- **Type:** Space Grotesk (headings), Inter (body), JetBrains Mono (code, JSON, tool calls), loaded from Google Fonts in `index.html`.
- **Layout:** every page works down to 390 px wide.

## Notes

- **Seller access:** there are no logins. A shop's seller token lives in this browser (`myShops.ts`); the dashboard's **Copy seller link** opens the shop elsewhere. Without the token, the dashboard shows "This dashboard is private" and the setup/review pages show "Seller access required".
- **Upload limits:** photos upload 3 at a time, with the same type and size limits as the backend (JPG/PNG/WebP/GIF, 5 MB).
- **Price input:** whole dollars are fine. `100` becomes `100.00` when you leave the field, using the same rules as the backend.
