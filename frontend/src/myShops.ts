// Shops this browser created or opened, so the nav can link "Shop setup"
// and "Dashboard" straight to the seller's shop. There are no logins: each
// shop's seller token (returned once, when the shop is created) is kept here
// and sent with every seller request (api.ts). Lose it and the shop can only
// be opened again with a seller link (/sell/<id>/dashboard#seller=<token>).
// localStorage can throw (private mode, blocked storage): every access is
// guarded, and the site works without it (links fall back to /sell).

import { useEffect, useState } from 'react'

export type MyShop = { id: string; name: string; token?: string }

const KEY = 'shopmcp.myShops.v1'
const EVENT = 'app:myshops'
const MAX = 10

// Fallback when localStorage is blocked: tokens still work until the tab closes.
const memoryTokens = new Map<string, string>()

export function getMyShops(): MyShop[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(parsed) ? parsed.filter((s): s is MyShop => typeof s?.id === 'string') : []
  } catch {
    return []
  }
}

/** Move (or add) a shop to the front of the list: most recent first.
 * Keeps the shop's saved token unless a new one is given. */
export function rememberShop(id: string, name: string, token?: string) {
  if (token) memoryTokens.set(id, token)
  const old = getMyShops().find((s) => s.id === id)
  const entry: MyShop = { id, name: name || old?.name || 'My shop', token: token ?? old?.token }
  const list = [entry, ...getMyShops().filter((s) => s.id !== id)].slice(0, MAX)
  try {
    localStorage.setItem(KEY, JSON.stringify(list))
  } catch {
    return
  }
  window.dispatchEvent(new Event(EVENT))
}

export function getSellerToken(shopId: string): string | undefined {
  return getMyShops().find((s) => s.id === shopId)?.token ?? memoryTokens.get(shopId)
}

/** Seller link: opens the shop's dashboard in another browser. The token is
 * in the #fragment, which browsers never send to the server. */
export function sellerLink(shopId: string): string | undefined {
  const token = getSellerToken(shopId)
  return token ? `${window.location.origin}/sell/${shopId}/dashboard#seller=${token}` : undefined
}

/** On page load: if the URL is a seller link, save its token and remove it
 * from the address bar (so it isn't bookmarked or shared by accident). */
export function importSellerLink() {
  const token = new URLSearchParams(window.location.hash.slice(1)).get('seller')
  const shopId = window.location.pathname.match(/^\/sell\/([^/]+)/)?.[1]
  if (!token || !shopId) return
  rememberShop(shopId, '', token)
  window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search)
}

/** Re-renders when the list changes (this tab or another). */
export function useMyShops(): MyShop[] {
  const [shops, setShops] = useState(getMyShops)
  useEffect(() => {
    const update = () => setShops(getMyShops())
    window.addEventListener(EVENT, update)
    window.addEventListener('storage', update) // other tabs
    return () => {
      window.removeEventListener(EVENT, update)
      window.removeEventListener('storage', update)
    }
  }, [])
  return shops
}
