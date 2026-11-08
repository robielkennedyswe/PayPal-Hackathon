// Shops this browser created or opened, so the nav can link "Shop setup"
// and "Dashboard" straight to the seller's shop. There are no logins, so
// this per-browser memory is the seller's way back to their dashboard.
// localStorage can throw (private mode, blocked storage): every access is
// guarded, and the site works without it (links fall back to /sell).

import { useEffect, useState } from 'react'

export type MyShop = { id: string; name: string }

const KEY = 'shopmcp.myShops.v1'
const EVENT = 'app:myshops'
const MAX = 10

export function getMyShops(): MyShop[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(parsed) ? parsed.filter((s): s is MyShop => typeof s?.id === 'string') : []
  } catch {
    return []
  }
}

/** Move (or add) a shop to the front of the list: most recent first. */
export function rememberShop(id: string, name: string) {
  const list = [{ id, name }, ...getMyShops().filter((s) => s.id !== id)].slice(0, MAX)
  try {
    localStorage.setItem(KEY, JSON.stringify(list))
  } catch {
    return
  }
  window.dispatchEvent(new Event(EVENT))
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
