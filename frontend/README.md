# ShopMCP frontend

React 19 + Vite + TypeScript. Seller screens (add products, review & publish), the public storefront, and the checkout result page.

## Setup & scripts

Requires Node.js 20.19+ or 22.12+.

```bash
npm install
npm run dev       # http://localhost:5173
npm run build     # type-check + production build into dist/
npm run lint      # oxlint
npm run preview   # serve the production build
```

The backend must be running on `:8000` (see [backend/README.md](../backend/README.md)). In development, Vite proxies `/api`, `/mcp`, `/paypal` and `/uploads` to it (`vite.config.ts`), so the app calls relative URLs and needs no CORS setup.

## Routes

| Path | Page | What it does |
|---|---|---|
| `/` | `Home` | Landing page with "Start selling" |
| `/sell`, `/sell/:shopId` | `AddProducts` (screen 1) | Shop name + PayPal email, photo drop zone, AI draft cards. The first upload creates the shop, and the URL gains the shop id so a refresh resumes it. |
| `/sell/:shopId/review` | `Review` (screen 2) | Edit each listing (saves when you leave a field), live "What AI agents will see" JSON, Publish, link to the storefront |
| `/s/:slug` | `Storefront` | Public page for a published shop: live prices, stock, sold-out badges |
| `/checkout/result` | `CheckoutResult` | Where buyers land after PayPal (`?status=…&order=…`) |

## Structure

```
src/
  main.tsx            entry; loads index.css (tokens) + app.css (components)
  App.tsx             route table
  router.ts           tiny History-API router: navigate(), useLocation(), matchPath()
  components/
    Link.tsx          client-side <a>
    TopBar.tsx        brand bar + seller progress steps
  pages/              Home, AddProducts, Review, Storefront, CheckoutResult
  api.ts              typed fetch wrappers for the backend; FastAPI errors → ApiError
  types.ts            types mirroring backend/app/schemas.py; normalizePrice()
  agentView.ts        listing JSON as AI agents receive it (must match the MCP get_product tool)
  index.css           design tokens + base styles
  app.css             component styles
```

**Why no react-router?** The app has five fixed routes, so a ~40-line router does the job without adding a dependency. Back/forward and refresh work, because URLs are real paths.

## Design

Tokens are CSS variables in `src/index.css`. Components use the variables, never raw hex values.

- **Colors:**
  - warm off-white `--bg` `#FBFAF7` and ink `--ink` `#17181C`
  - **seller teal** `--seller` `#0B6B58`
  - **agent indigo** `--agent` `#4338CA`
- **Type:** Space Grotesk (headings), Inter (body), JetBrains Mono (code, JSON, tool calls), loaded from Google Fonts in `index.html`.
- **Layout:** every page works down to 390 px wide.

## Notes

- **Upload limits:** photos upload 3 at a time, with the same type and size limits as the backend (JPG/PNG/WebP/GIF, 5 MB).
- **Price input:** whole dollars are fine. `100` becomes `100.00` when you leave the field, using the same rules as the backend.
- **Deployment (to do):** the dev proxy doesn't exist in production. The hosted build will need the backend URL, either through a `VITE_API_BASE_URL` prefix in `api.ts` or by serving `dist/` from FastAPI.
