import { Link } from '../components/Link'
import { ShopGrid } from '../components/ShopGrid'
import { TopBar } from '../components/TopBar'
import { useShops } from '../useShops'

const HOW = [
  { side: 'seller', title: 'Snap your products', text: 'Drop in photos. AI writes the title, description, tags and a suggested price.' },
  { side: 'seller', title: 'Review & publish', text: 'Tweak price and stock, then publish. Your shop gets an MCP endpoint.' },
  { side: 'agent', title: 'AI agents can buy', text: 'Any MCP-compatible agent can search and check out. Buyers approve every payment in PayPal.' },
] as const

const HOME_SHOPS = 6

export function Home() {
  const { shops } = useShops()
  return (
    <>
      <TopBar />
      <main className="page">
        <section className="hero">
          <h1>Make any tiny shop buyable by AI agents.</h1>
          <p>
            Turn product photos into AI-ready listings in minutes. Agents find your products and check out
            with PayPal. You just ship.
          </p>
          <div className="hero-actions">
            <Link href="/sell" className="btn btn-primary">
              Start selling
            </Link>
            <Link href="/agent" className="btn btn-agent">
              Shop with an AI agent
            </Link>
          </div>
        </section>
        <section className="how" aria-label="How it works">
          {HOW.map((h) => (
            <article key={h.title} className="card">
              <span className={`chip ${h.side}`}>{h.side}</span>
              <h3>{h.title}</h3>
              <p>{h.text}</p>
            </article>
          ))}
        </section>
        {shops && shops.length > 0 && (
          <section className="home-shops" aria-label="Shops on ShopMCP">
            <div className="section-head">
              <h2>Shops on ShopMCP</h2>
              {shops.length > HOME_SHOPS && (
                <Link href="/shops" className="btn btn-sm">
                  See all {shops.length} shops →
                </Link>
              )}
            </div>
            <ShopGrid shops={shops} limit={HOME_SHOPS} />
          </section>
        )}
      </main>
    </>
  )
}
