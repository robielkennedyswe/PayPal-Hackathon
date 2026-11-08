// Loads the public shop directory (GET /api/storefronts).

import { useEffect, useState } from 'react'
import { api } from './api'
import type { ShopCard } from './types'

export function useShops() {
  const [shops, setShops] = useState<ShopCard[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    api
      .listStorefronts()
      .then((s) => !cancelled && setShops(s))
      .catch((e: Error) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [])
  return { shops, error }
}
