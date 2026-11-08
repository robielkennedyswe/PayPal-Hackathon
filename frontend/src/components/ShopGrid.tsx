// Grid of public shop cards, used by /shops and the home page.

import type { ShopCard } from '../types'
import { Link } from './Link'

export function ShopGrid({ shops, limit }: { shops: ShopCard[]; limit?: number }) {
  const shown = limit ? shops.slice(0, limit) : shops
  return (
    <div className="shop-grid">
      {shown.map((s) => (
        <ShopCardView key={s.slug} shop={s} />
      ))}
    </div>
  )
}

function ShopCardView({ shop: s }: { shop: ShopCard }) {
  const price = s.price_min === s.price_max ? `$${s.price_min}` : `$${s.price_min}–$${s.price_max}`
  return (
    <Link href={`/s/${s.slug}`} className="card shop-card">
      <div className={`shop-mosaic n${Math.max(1, s.images.length)}`} aria-hidden="true">
        {s.images.length === 0 ? <span className="shop-mosaic-empty" /> : s.images.map((src) => <img key={src} src={src} alt="" loading="lazy" />)}
      </div>
      <div className="shop-card-body">
        <h3>{s.name}</h3>
        <p className="muted">
          {s.product_count} product{s.product_count === 1 ? '' : 's'} · {price}
        </p>
        <span className="chip agent">● Live to AI agents</span>
        {s.in_stock_count === 0 && <span className="shop-soldout">Sold out</span>}
      </div>
    </Link>
  )
}
