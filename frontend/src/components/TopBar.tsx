import { useLocation } from '../router'
import { Link } from './Link'

const STEPS = ['Add products', 'Review & publish', 'Go live'] as const

const NAV = [
  { href: '/shops', label: 'Shops' },
  { href: '/agent', label: 'Shopper agent' },
  { href: '/sell', label: 'Sell' },
] as const

/** Brand bar. Seller flow pages pass `step` (1-based) to show progress
 * instead of the site nav, keeping the seller focused on finishing setup. */
export function TopBar({ step }: { step?: 1 | 2 | 3 }) {
  const { pathname } = useLocation()
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link href="/" className="brand-link">
          <img src="/favicon.svg" alt="" />
          ShopMCP
        </Link>
        {!step && (
          <nav className="site-nav" aria-label="Main">
            {NAV.map((n) => {
              const active = pathname === n.href || (n.href === '/shops' && pathname.startsWith('/s/'))
              return (
                <Link key={n.href} href={n.href} className={active ? 'active' : ''} aria-current={active ? 'page' : undefined}>
                  {n.label}
                </Link>
              )
            })}
          </nav>
        )}
        {step && (
          <ol className="steps" aria-label="Seller setup progress">
            {STEPS.map((label, i) => {
              const n = i + 1
              const state = n === step ? 'current' : n < step ? 'done' : ''
              return (
                <li key={label} className={state} aria-current={n === step ? 'step' : undefined}>
                  <span className="num">{n < step ? '✓' : n}</span>
                  <span className="label">{label}</span>
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </header>
  )
}
