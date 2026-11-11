import { useMyShops } from '../myShops'
import { matchPath, useLocation } from '../router'
import { Link } from './Link'

type NavItem = { label: string; short?: string; href: string; active: boolean }

/** Site header (matches the Claude Design top bar): brand, main nav with the
 * current section underlined, and a "PayPal sandbox" badge so nobody mistakes
 * test payments for real ones. */

export function TopBar() {
  const { pathname } = useLocation()
  // Only shops this browser can manage (has a seller token for) count as "yours".
  const myShops = useMyShops().filter((s) => s.token)

  // "Your shop": the one in the URL if we're on a seller page, else the most
  // recent. A URL shop this browser can't manage (no or rejected token) doesn't count.
  const urlShop = (matchPath('/sell/:shopId', pathname) ??
    matchPath('/sell/:shopId/review', pathname) ??
    matchPath('/sell/:shopId/dashboard', pathname))?.shopId
  const shopId = (urlShop && myShops.some((s) => s.id === urlShop) ? urlShop : undefined) ?? myShops[0]?.id

  const onSetup = pathname === '/sell' || (pathname.startsWith('/sell/') && !pathname.endsWith('/dashboard'))
  // Shoppers see "Start selling"; sellers (a shop in this browser) get setup + dashboard.
  const sellerLinks: NavItem[] = shopId
    ? [
        { label: 'Shop setup', href: `/sell/${shopId}`, active: onSetup },
        { label: 'Dashboard', href: `/sell/${shopId}/dashboard`, active: pathname.endsWith('/dashboard') },
      ]
    : [{ label: 'Start selling', href: '/sell', active: pathname.startsWith('/sell') }]
  const nav: NavItem[] = [
    { label: 'Shops', href: '/shops', active: pathname === '/shops' || pathname.startsWith('/s/') },
    ...sellerLinks,
    { label: 'Try the shopper agent', short: 'Shopper agent', href: '/agent', active: pathname === '/agent' },
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
              className={n.active ? 'active' : ''}
              aria-current={n.active ? 'page' : undefined}
            >
              {n.short ? (
                <>
                  <span className="nav-long">{n.label}</span>
                  <span className="nav-short">{n.short}</span>
                </>
              ) : (
                n.label
              )}
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
