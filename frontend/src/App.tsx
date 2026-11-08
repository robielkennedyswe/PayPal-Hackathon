import { TopBar } from './components/TopBar'
import { Link } from './components/Link'
import { AddProducts } from './pages/AddProducts'
import { CheckoutResult } from './pages/CheckoutResult'
import { Dashboard } from './pages/Dashboard'
import { Home } from './pages/Home'
import { Review } from './pages/Review'
import { ShopperAgent } from './pages/ShopperAgent'
import { Shops } from './pages/Shops'
import { Storefront } from './pages/Storefront'
import { matchPath, useLocation } from './router'

export default function App() {
  const { pathname, search } = useLocation()

  if (pathname === '/') return <Home />

  // /sell and /sell/:shopId render the same component from the same spot,
  // so React keeps its state when the URL gains the new shop id.
  const sell = matchPath('/sell', pathname) ?? matchPath('/sell/:shopId', pathname)
  if (sell) return <AddProducts shopId={sell.shopId} />

  const review = matchPath('/sell/:shopId/review', pathname)
  if (review) return <Review shopId={review.shopId} />

  const dash = matchPath('/sell/:shopId/dashboard', pathname)
  if (dash) return <Dashboard shopId={dash.shopId} />

  const store = matchPath('/s/:slug', pathname)
  if (store) return <Storefront slug={store.slug} />

  if (pathname === '/agent') return <ShopperAgent />

  if (pathname === '/shops') return <Shops />

  if (pathname === '/checkout/result') return <CheckoutResult search={search} />

  return (
    <>
      <TopBar />
      <main className="page">
        <h1>Page not found</h1>
        <p className="muted" style={{ margin: '8px 0 16px' }}>
          Nothing lives at <span className="mono">{pathname}</span>.
        </p>
        <Link href="/" className="btn">
          Go home
        </Link>
      </main>
    </>
  )
}
