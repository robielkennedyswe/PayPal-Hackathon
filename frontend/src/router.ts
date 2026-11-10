// Minimal client-side router: a handful of fixed routes doesn't need a
// library. Uses the History API so URLs are real paths (/sell/shop_123),
// back/forward work, and refresh keeps your place.

import { useEffect, useState } from 'react'

const NAV_EVENT = 'app:navigate'

// A page with unsaved edits can ask before in-app navigation (Link clicks,
// navigate()). Closing or reloading the tab is covered by beforeunload.
let leaveGuard: (() => boolean) | null = null
export function setLeaveGuard(guard: (() => boolean) | null) {
  leaveGuard = guard
}

export function navigate(to: string, { replace = false } = {}) {
  if (leaveGuard && !leaveGuard()) return
  if (replace) window.history.replaceState(null, '', to)
  else window.history.pushState(null, '', to)
  window.dispatchEvent(new Event(NAV_EVENT))
  window.scrollTo(0, 0)
}

/** Current location; re-renders on navigate() and on back/forward. */
export function useLocation() {
  const read = () => ({ pathname: window.location.pathname, search: window.location.search })
  const [loc, setLoc] = useState(read)
  useEffect(() => {
    const update = () => setLoc(read())
    window.addEventListener('popstate', update)
    window.addEventListener(NAV_EVENT, update)
    return () => {
      window.removeEventListener('popstate', update)
      window.removeEventListener(NAV_EVENT, update)
    }
  }, [])
  return loc
}

/**
 * Match "/sell/:shopId/review" against a pathname.
 * Returns the params on a match, otherwise null.
 */
export function matchPath(pattern: string, pathname: string): Record<string, string> | null {
  const p = pattern.split('/').filter(Boolean)
  const s = pathname.split('/').filter(Boolean)
  if (p.length !== s.length) return null
  const params: Record<string, string> = {}
  for (let i = 0; i < p.length; i++) {
    if (p[i].startsWith(':')) params[p[i].slice(1)] = decodeURIComponent(s[i])
    else if (p[i] !== s[i]) return null
  }
  return params
}
