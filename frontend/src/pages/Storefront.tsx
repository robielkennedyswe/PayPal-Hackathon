// Public storefront for a published shop: /s/:slug
// Shows live products with current prices and stock. Buying happens through
// AI agents (MCP), so there's no cart here, just a "how to buy" note.

import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import { Link } from '../components/Link'
import { TopBar } from '../components/TopBar'
import type { Product, Storefront as StorefrontData } from '../types'

export function Storefront({ slug }: { slug: string }) {
  const [shop, setShop] = useState<StorefrontData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .getStorefront(slug)
      .then((s) => !cancelled && setShop(s))
      .catch((e: Error) => {
        if (cancelled) return
        setError(e instanceof ApiError && e.status === 404 ? 'not_found' : e.message)
      })
    return () => {
      cancelled = true
    }
  }, [slug])

  if (error) {
    return (
      <>
        <TopBar />
        <main className="page">
          <h1>{error === 'not_found' ? 'Shop not found' : 'Something went wrong'}</h1>
          <p className="muted" style={{ margin: '8px 0 16px' }}>
            {error === 'not_found' ? "This shop doesn't exist or hasn't been published yet." : error}
          </p>
          <Link href="/" className="btn">
            Go home
          </Link>
        </main>
      </>
    )
  }
  if (!shop) {
    return (
      <>
        <TopBar />
        <main className="page muted">Loading…</main>
      </>
    )
  }

  const count = shop.products.length
  return (
    <>
      <TopBar />
      <main className="page">
        <header className="store-head">
          <span className="chip agent">● Live to AI agents</span>
          <h1>{shop.name}</h1>
          <p className="muted">
            {count} product{count === 1 ? '' : 's'} · Prices in USD
          </p>
        </header>

        <div className="store-layout">
          <section className="store-grid" aria-label="Products">
            {shop.products.map((p) => (
              <ProductCard key={p.id} product={p} />
            ))}
          </section>

          <aside className="card card-pad how-to-buy">
            <h2>How to buy</h2>
            <p className="muted">
              {shop.name} sells through AI shopping agents. Ask any MCP-connected agent to find and buy from this
              shop.
            </p>
            <p className="muted">
              You always approve the payment yourself in <strong>PayPal</strong>. The agent can never pay on its own.
            </p>
          </aside>
        </div>
      </main>
    </>
  )
}

function ProductCard({ product: p }: { product: Product }) {
  const soldOut = p.stock <= 0
  return (
    <article className={`card store-card${soldOut ? ' sold-out' : ''}`}>
      <div className="store-img">
        {p.image_url && <img src={p.image_url} alt={p.title} loading="lazy" />}
        {soldOut && <span className="sold-badge">Sold out</span>}
      </div>
      <div className="store-body">
        <h3>{p.title}</h3>
        <div className="store-meta">
          <span className="draft-price">${p.price}</span>
          <span className={`stock-note${!soldOut && p.stock <= 2 ? ' low' : ''}`}>
            {soldOut ? 'Out of stock' : p.stock <= 2 ? `Only ${p.stock} left` : `${p.stock} in stock`}
          </span>
        </div>
        <p className="store-desc">{p.description}</p>
        <div className="tags">
          {p.tags.slice(0, 4).map((t) => (
            <span key={t} className="tag">
              {t}
            </span>
          ))}
        </div>
      </div>
    </article>
  )
}
