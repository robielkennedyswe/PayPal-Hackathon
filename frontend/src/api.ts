// Typed wrappers around the FastAPI routes. In dev, relative URLs go
// through the Vite proxy to :8000. (Deploy: prefix with the backend URL.)

import type { Product, ProductUpdate, Shop } from './types'

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
      else if (Array.isArray(body.detail) && body.detail[0]?.msg) message = body.detail[0].msg
    } catch {
      /* non-JSON error body: keep the generic message */
    }
    throw new ApiError(res.status, message)
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  createShop: (name: string, paypal_payee_email: string) =>
    request<Shop>('/api/shops', json('POST', { name, paypal_payee_email })),

  getShop: (shopId: string) => request<Shop>(`/api/shops/${shopId}`),

  uploadPhoto: (shopId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<Product>(`/api/shops/${shopId}/products`, { method: 'POST', body: form })
  },

  updateProduct: (productId: string, changes: ProductUpdate) =>
    request<Product>(`/api/products/${productId}`, json('PATCH', changes)),

  deleteProduct: (productId: string) =>
    request<void>(`/api/products/${productId}`, { method: 'DELETE' }),

  publishShop: (shopId: string) => request<Shop>(`/api/shops/${shopId}/publish`, { method: 'POST' }),
}
