import { useMyShops } from '../myShops'
import { matchPath, useLocation } from '../router'
import { Link } from './Link'

/** Site header (matches the Claude Design top bar): brand, main nav with the
 * current section underlined, and a "PayPal sandbox" badge so nobody mistakes
 * test payments for real ones. */
export function TopBar() {
  const { pathname } = useLocation()
  const myShops = useMyShops()

  // "Your shop": the one in the URL if we're on a seller page, else the most recent.
  const urlShop = (matchPath('/sell/:shopId', pathname) ??
    matchPath('/sell/:shopId/review', pathname) ??
    matchPath('/sell/:shopId/dashboard', pathname))?.shopId
  const shopId = urlShop ?? myShops[0]?.id

  const onSetup = pathname === '/sell' || (pathname.startsWith('/sell/') && !pathname.endsWith('/dashboard'))
  const nav = [
    { label: 'Shops', href: '/shops', active: pathname === '/shops' || pathname.startsWith('/s/') },
    { label: 'Shop setup', href: shopId ? `/sell/${shopId}` : '/sell', active: onSetup },
    {
      label: 'Dashboard',
      href: shopId ? `/sell/${shopId}/dashboard` : '/sell',
      active: pathname.endsWith('/dashboard'),
      title: shopId ? undefined : 'Create a shop first',
    },
    { label: 'Try the shopper agent', href: '/agent', active: pathname === '/agent' },
  ]

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link href="/" className="brand-link">
          <img src="/favicon.svg" alt="" />
          ShopMCP
        </Link>
        <nav className="site-nav" aria-label="Main">
          {nav.map((n) => (
            <Link
              key={n.label}
              href={n.href}
              title={n.title}
              className={n.active ? 'active' : ''}
              aria-current={n.active ? 'page' : undefined}
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <span className="sandbox-badge" title="Payments use PayPal's sandbox: test money only">
          PayPal sandbox
        </span>
      </div>
    </header>
  )
}
