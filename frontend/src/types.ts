// Mirrors backend/app/schemas.py. Keep the two in sync.

export type Product = {
  id: string
  shop_id: string
  title: string
  description: string
  attributes: Record<string, string | number | boolean>
  tags: string[]
  price: string // USD decimal string, "34.00"
  stock: number
  image_url: string | null
  created_at: string
}

export type Shop = {
  id: string
  slug: string
  name: string
  paypal_payee_email: string
  published: boolean
  created_at: string
  products: Product[]
}

/** Public storefront: published shops only, no seller email. */
export type Storefront = {
  name: string
  slug: string
  products: Product[]
}

export type ProductUpdate = Partial<Pick<Product, 'title' | 'description' | 'price' | 'stock' | 'tags'>>

export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

/**
 * "20" -> "20.00", "20.5" -> "20.50", "$1,200" -> "1200.00".
 * Returns null if the input isn't a price. Mirrors normalize_price() in
 * backend/app/schemas.py. String math only, so no float rounding.
 */
export function normalizePrice(input: string): string | null {
  const s = input.trim().replace(/^\$/, '').replace(/,/g, '').trim()
  const m = /^(\d{1,6})(?:\.(\d{0,2}))?$/.exec(s)
  if (!m) return null
  return `${parseInt(m[1], 10)}.${(m[2] ?? '').padEnd(2, '0')}`
}
