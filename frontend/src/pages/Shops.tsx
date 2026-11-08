// Public directory of every published shop: /shops

import { Link } from '../components/Link'
import { ShopGrid } from '../components/ShopGrid'
import { TopBar } from '../components/TopBar'
import { useShops } from '../useShops'

export function Shops() {
  const { shops, error } = useShops()
  return (
    <>
      <TopBar />
      <main className="page">
        <header className="page-head">
          <div>
            <h1>Browse shops</h1>
            <p>Every shop here is live to AI agents. Browse their storefronts, or let an agent shop for you.</p>
          </div>
          <Link href="/agent" className="btn btn-agent">
            Shop with an AI agent
          </Link>
        </header>
        {error && <div className="banner banner-error">Couldn't load shops: {error}</div>}
        {!shops && !error && <p className="muted">Loading…</p>}
        {shops && shops.length === 0 && (
          <div className="card card-pad empty-shops">
            <p className="muted">No shops are live yet.</p>
            <Link href="/sell" className="btn btn-primary">
              Open the first one
            </Link>
          </div>
        )}
        {shops && shops.length > 0 && <ShopGrid shops={shops} />}
      </main>
    </>
  )
}
