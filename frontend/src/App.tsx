import { TopBar } from './components/TopBar'
import { Link } from './components/Link'
import { AddProducts } from './pages/AddProducts'
import { Home } from './pages/Home'
import { matchPath, useLocation } from './router'

export default function App() {
  const { pathname } = useLocation()

  if (pathname === '/') return <Home />

  // /sell and /sell/:shopId render the same component from the same spot,
  // so React keeps its state when the URL gains the new shop id.
  const sell = matchPath('/sell', pathname) ?? matchPath('/sell/:shopId', pathname)
  if (sell) return <AddProducts shopId={sell.shopId} />

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
