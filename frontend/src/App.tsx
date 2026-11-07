// Placeholder shell: shows the design tokens working and lists the four
// screens. Each card is replaced by a real page (and a router) as it's built.

type Screen = {
  title: string
  summary: string
  side: 'seller' | 'agent'
}

const SCREENS: Screen[] = [
  { title: 'Add products', summary: 'Shop name, PayPal email, photo drop zone; AI drafts listings.', side: 'seller' },
  { title: 'Review & publish', summary: 'Edit title, price, stock. See what AI agents will see.', side: 'seller' },
  { title: 'Seller dashboard', summary: 'MCP endpoint, live activity feed, inventory.', side: 'seller' },
  { title: 'Shopper agent', summary: 'Chat with an AI agent that searches and buys via PayPal.', side: 'agent' },
]

export default function App() {
  return (
    <main className="shell">
      <header className="brand">
        <img src="/favicon.svg" alt="" />
        <h1>ShopMCP</h1>
      </header>
      <p className="tagline">Make any tiny shop buyable by AI agents.</p>
      <section className="screens">
        {SCREENS.map((s) => (
          <article key={s.title} className="screen-card">
            <span className={`chip ${s.side}`}>{s.side}</span>
            <h2>{s.title}</h2>
            <p>{s.summary}</p>
          </article>
        ))}
      </section>
    </main>
  )
}
