// Screen 3: seller dashboard at /sell/:shopId/dashboard.
// "Live to AI agents" banner with the MCP endpoint, stats, a live activity
// feed (search -> view -> checkout -> approved -> sold), inventory, and how
// to connect an agent. Polls every few seconds; only new events are fetched.

import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import { Link } from '../components/Link'
import { TopBar } from '../components/TopBar'
import { rememberShop, sellerLink, useMyShops } from '../myShops'
import { navigate } from '../router'
import { timeAgo } from '../time'
import type { ActivityEvent, Dashboard as DashboardData } from '../types'

const POLL_MS = 3000
const FEED_MAX = 100 // keep the in-page feed bounded on a long-running tab

export function Dashboard({ shopId }: { shopId: string }) {
  const [data, setData] = useState<DashboardData | null>(null)
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [fresh, setFresh] = useState<Set<number>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [, setTick] = useState(0) // re-render so "2m ago" stays current
  const myShops = useMyShops()
  const lastId = useRef(0)

  useEffect(() => {
    let cancelled = false
    let first = true
    let timer: number | undefined

    async function load() {
      if (!first && document.hidden) return schedule() // don't poll a background tab
      try {
        const d = await api.getDashboard(shopId, lastId.current)
        if (cancelled) return
        setData(d)
        if (first) rememberShop(d.shop.id, d.shop.name)
        setError(null)
        if (d.events.length > 0) {
          lastId.current = Math.max(lastId.current, ...d.events.map((e) => e.id))
          setEvents((prev) => [...d.events, ...prev].slice(0, FEED_MAX))
          // Highlight events that arrive while the page is open (not the initial load).
          if (!first) setFresh(new Set(d.events.map((e) => e.id)))
        }
        first = false
      } catch (e) {
        if (cancelled) return
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
          setError('no_access')
          return // no point polling: this browser has no (valid) seller token
        }
        setError(e instanceof ApiError && e.status === 404 ? 'not_found' : (e as Error).message)
      }
      setTick((t) => t + 1)
      schedule()
    }
    function schedule() {
      if (!cancelled) timer = window.setTimeout(load, POLL_MS)
    }

    void load()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [shopId])

  if (error === 'not_found') {
    return (
      <>
        <TopBar />
        <main className="page">
          <h1>Shop not found</h1>
          <Link href="/sell" className="btn" style={{ marginTop: 16 }}>
            Start a new shop
          </Link>
        </main>
      </>
    )
  }
  if (error === 'no_access') {
    return (
      <>
        <TopBar />
        <main className="page">
          <h1>This dashboard is private</h1>
          <p className="muted" style={{ marginTop: 8 }}>
            Only the seller can see it. Open it in the browser that created the shop, or use the seller link
            copied from that browser's dashboard.
          </p>
          <Link href="/shops" className="btn" style={{ marginTop: 16 }}>
            Browse shops
          </Link>
        </main>
      </>
    )
  }
  if (!data) {
    return (
      <>
        <TopBar />
        <main className="page muted">{error ? `Couldn't load the dashboard: ${error}` : 'Loading…'}</main>
      </>
    )
  }

  const { shop, stats } = data
  const lastSale = events.find((e) => e.kind === 'sold' && fresh.has(e.id))

  return (
    <>
      <TopBar />
      <main className="page dashboard">
        <header className="page-head">
          <div>
            <h1>{shop.name}</h1>
            <p>Seller dashboard · updates live</p>
            {myShops.length > 1 && (
              <label className="shop-switch">
                <span>Your shops</span>
                <select
                  className="input"
                  value={shop.id}
                  onChange={(e) => navigate(`/sell/${e.target.value}/dashboard`)}
                >
                  {myShops.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <div className="head-actions">
            <CopySellerLink shopId={shop.id} />
            <Link href={`/sell/${shop.id}/review`} className="btn">
              Edit listings
            </Link>
            {shop.published && (
              <Link href={`/s/${shop.slug}`} className="btn">
                View storefront
              </Link>
            )}
          </div>
        </header>

        {error && <div className="banner banner-error">Connection problem, retrying… ({error})</div>}
        {lastSale && (
          <div className="banner sale-banner" role="status">
            <strong>Sold via AI agent!</strong> {lastSale.detail.qty} × {lastSale.product_title} · $
            {lastSale.detail.amount}
          </div>
        )}

        {shop.published ? (
          <LiveBanner mcpUrl={data.mcp_url} />
        ) : (
          <div className="banner banner-error not-live">
            <strong>Not live yet.</strong> AI agents can't see this shop until you publish it.{' '}
            <Link href={`/sell/${shop.id}/review`}>Review &amp; publish →</Link>
          </div>
        )}

        <section className="stats" aria-label="Shop stats">
          <Stat label="Agent searches" value={stats.searches} hint="searches that surfaced your products" />
          <Stat label="Product views" value={stats.views} hint="agents opened a listing" />
          <Stat label="Checkouts started" value={stats.checkouts} hint="PayPal orders created" />
          <Stat label="Sales" value={stats.sales} hint={`${stats.units_sold} unit${stats.units_sold === 1 ? '' : 's'} sold`} />
          <Stat label="Revenue" value={`$${formatMoney(stats.revenue)}`} hint="captured in PayPal (sandbox)" />
        </section>

        <div className="dash-grid">
          <section className="card card-pad feed" aria-label="Live activity">
            <div className="feed-head">
              <h2>Live activity</h2>
              <span className="live-dot" aria-hidden="true" /> <span className="muted feed-live">Live</span>
            </div>
            {events.length === 0 ? (
              <div className="feed-empty">
                <p className="muted">No agent activity yet.</p>
                <p className="muted">
                  Try it: open the <Link href="/agent">built-in shopper agent</Link> and ask for one of your products.
                  Its searches and purchases show up here within seconds.
                </p>
              </div>
            ) : (
              <ol className="feed-list">
                {events.map((e) => (
                  <FeedItem key={e.id} event={e} fresh={fresh.has(e.id)} />
                ))}
              </ol>
            )}
          </section>

          <ConnectCard mcpUrl={data.mcp_url} />
        </div>

        <section className="card inventory" aria-label="Inventory">
          <div className="inventory-head">
            <h2>Inventory</h2>
            <Link href={`/sell/${shop.id}/review`} className="btn btn-sm">
              Edit prices &amp; stock
            </Link>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">Product</th>
                  <th scope="col" className="num">
                    Price
                  </th>
                  <th scope="col" className="num">
                    In stock
                  </th>
                  <th scope="col" className="num">
                    Sold
                  </th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {shop.products.map((p) => {
                  const status = !shop.published ? 'draft' : p.stock <= 0 ? 'out' : p.stock <= 2 ? 'low' : 'live'
                  return (
                    <tr key={p.id}>
                      <td>
                        <div className="inv-product">
                          {p.image_url ? <img src={p.image_url} alt="" /> : <span className="inv-noimg" />}
                          <span>{p.title}</span>
                        </div>
                      </td>
                      <td className="num">${p.price}</td>
                      <td className="num">{p.stock}</td>
                      <td className="num">{data.units_sold[p.id] ?? 0}</td>
                      <td>
                        <span className={`inv-status ${status}`}>{STATUS_LABEL[status]}</span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </>
  )
}

const STATUS_LABEL = { draft: 'Draft', out: 'Sold out', low: 'Low stock', live: 'Live' } as const

function Stat({ label, value, hint }: { label: string; value: number | string; hint: string }) {
  return (
    <div className="card stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{typeof value === 'number' ? value.toLocaleString('en-US') : value}</span>
      <span className="stat-hint">{hint}</span>
    </div>
  )
}

// ---------- banner + connect ----------

function LiveBanner({ mcpUrl }: { mcpUrl: string }) {
  return (
    <section className="live-banner" aria-label="Your MCP endpoint">
      <div>
        <span className="live-pill">
          <span className="live-dot" aria-hidden="true" /> Live to AI agents
        </span>
        <p>Any MCP-compatible AI agent can search your products and start a PayPal checkout at:</p>
      </div>
      <CopyField value={mcpUrl} label="MCP endpoint" />
    </section>
  )
}

function ConnectCard({ mcpUrl }: { mcpUrl: string }) {
  const isLocal = /localhost|127\.0\.0\.1/.test(mcpUrl)
  return (
    <aside className="card card-pad connect" aria-label="Connect an AI agent">
      <h2>Connect any AI agent</h2>
      <ol className="connect-steps">
        <li>
          <strong>Claude Code</strong>
          <CopyField value={`claude mcp add --transport http shopmcp ${mcpUrl}`} label="Claude Code command" />
        </li>
        <li>
          <strong>Claude Desktop or claude.ai</strong>
          <span className="muted">
            Settings → Connectors → Add custom connector, then paste the MCP endpoint.
            {isLocal && ' Needs the public (deployed) URL; localhost only works for local clients.'}
          </span>
        </li>
        <li>
          <strong>Any other MCP client</strong>
          <span className="muted">Add a remote server with streamable HTTP transport and the endpoint above.</span>
        </li>
        <li>
          <strong>No setup</strong>
          <span className="muted">
            Use the <Link href="/agent">built-in shopper agent</Link>. It uses the same tools.
          </span>
        </li>
      </ol>
      <p className="connect-note">Buyers always approve payment in PayPal. Agents can never pay on their own.</p>
    </aside>
  )
}

function CopyField({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard blocked (non-https or permissions): the text stays selectable */
    }
  }
  return (
    <div className="copy-field">
      <code aria-label={label}>{value}</code>
      <button type="button" className="btn btn-sm" onClick={copy}>
        {copied ? 'Copied ✓' : 'Copy'}
      </button>
    </div>
  )
}

/** Lets the seller open this dashboard on another device. The link contains
 * the seller token, so it's copied, never shown on screen (screen recordings). */
function CopySellerLink({ shopId }: { shopId: string }) {
  const [copied, setCopied] = useState(false)
  const link = sellerLink(shopId)
  if (!link) return null
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard blocked: nothing else to do; the link is deliberately not displayed */
    }
  }
  return (
    <button
      type="button"
      className="btn"
      onClick={copy}
      title="Copies a private link that opens this dashboard in another browser. Anyone with it can manage your shop."
    >
      {copied ? 'Seller link copied ✓' : 'Copy seller link'}
    </button>
  )
}

// ---------- feed ----------

const SOURCE_LABEL = { mcp: 'MCP agent', agent: 'Built-in agent', web: 'Web' } as const

function FeedItem({ event: e, fresh }: { event: ActivityEvent; fresh: boolean }) {
  const title = e.product_title ?? 'a product'
  const money = e.detail.amount ? ` · $${e.detail.amount}` : ''
  const qty = e.detail.qty ?? 1
  const text: Record<ActivityEvent['kind'], string> = {
    search: e.detail.query
      ? `Searched “${e.detail.query}”${e.detail.max_price ? ` under $${e.detail.max_price}` : ''}: ${e.detail.matches} of your products matched`
      : `Browsed the catalog: ${e.detail.matches} of your products listed`,
    view: `Viewed ${title}`,
    checkout: `Started PayPal checkout: ${qty} × ${title}${money}`,
    approved: `Buyer approved the payment in PayPal${money}`,
    sold: `Sold via AI agent: ${qty} × ${title}${money}`,
    cancelled: `Buyer cancelled the PayPal payment for ${title}`,
    missed: `${title} sold out before payment. Buyer was not charged`,
  }
  return (
    <li className={`feed-item ${e.kind}${fresh ? ' fresh' : ''}`}>
      <span className={`feed-icon ${e.kind}`} aria-hidden="true">
        {ICON[e.kind]}
      </span>
      <div className="feed-body">
        <span className="feed-text">{text[e.kind]}</span>
        <span className="feed-meta">
          <span className={`feed-source ${e.source}`}>{SOURCE_LABEL[e.source]}</span> · {timeAgo(e.created_at)}
        </span>
      </div>
    </li>
  )
}

const ICON: Record<ActivityEvent['kind'], string> = {
  search: '⌕',
  view: '◉',
  checkout: '⇢',
  approved: '✓',
  sold: '$',
  cancelled: '×',
  missed: '!',
}

/** "1234.50" -> "1,234.50" without going through floats for the cents. */
function formatMoney(amount: string): string {
  const [whole, cents = '00'] = amount.split('.')
  return `${Number(whole).toLocaleString('en-US')}.${cents.padEnd(2, '0')}`
}
