// Typed wrappers around the FastAPI routes. In dev, relative URLs go
// through the Vite proxy to :8000. (Deploy: prefix with the backend URL.)

import { getSellerToken } from './myShops'
import type { AgentHistory, AgentReply, Dashboard, Product, ProductUpdate, Shop, ShopCard, Storefront } from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    // FastAPI errors are {detail: string} or {detail: [{msg, loc}, ...]}.
    let message = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (typeof body.detail?.message === 'string') message = body.detail.message // {code, message}
      else if (Array.isArray(body.detail) && body.detail[0]?.msg) message = body.detail[0].msg
    } catch {
      /* non-JSON error body: keep the generic message */
    }
    throw new ApiError(res.status, message)
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

const json = (method: string, body: unknown, headers: Record<string, string> = {}): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json', ...headers },
  body: JSON.stringify(body),
})

/** Seller routes need the shop's token (see myShops.ts). Without one the
 * backend answers 401, which the pages show as "no access". */
const seller = (shopId: string): Record<string, string> => {
  const token = getSellerToken(shopId)
  return token ? { 'X-Seller-Token': token } : {}
}

export const api = {
  createShop: (name: string, paypal_payee_email: string) =>
    request<Shop & { seller_token: string }>('/api/shops', json('POST', { name, paypal_payee_email })),

  getShop: (shopId: string) => request<Shop>(`/api/shops/${shopId}`, { headers: seller(shopId) }),

  uploadPhoto: (shopId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<Product>(`/api/shops/${shopId}/products`, { method: 'POST', body: form, headers: seller(shopId) })
  },

  updateProduct: (shopId: string, productId: string, changes: ProductUpdate) =>
    request<Product>(`/api/products/${productId}`, json('PATCH', changes, seller(shopId))),

  deleteProduct: (shopId: string, productId: string) =>
    request<void>(`/api/products/${productId}`, { method: 'DELETE', headers: seller(shopId) }),

  listStorefronts: () => request<ShopCard[]>('/api/storefronts'),

  getStorefront: (slug: string) => request<Storefront>(`/api/storefront/${encodeURIComponent(slug)}`),

  publishShop: (shopId: string) => request<Shop>(`/api/shops/${shopId}/publish`, { method: 'POST', headers: seller(shopId) }),

  /** after = last event id already shown; only newer events come back. */
  getDashboard: (shopId: string, after = 0) =>
    request<Dashboard>(`/api/shops/${encodeURIComponent(shopId)}/dashboard?after=${after}`, {
      headers: seller(shopId),
    }),

  health: () => request<{ ok: boolean; ai_provider: 'mock' | 'anthropic' }>('/api/health'),

  agentChat: (history: AgentHistory, message: string) =>
    request<AgentReply>('/api/agent/chat', json('POST', { history, message })),

  getOrder: (orderId: string) =>
    request<{ id: string; status: string; amount: string; paypal_capture_id: string | null }>(
      `/api/orders/${encodeURIComponent(orderId)}`,
    ),
}
