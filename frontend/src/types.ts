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

export type ProductUpdate = Partial<Pick<Product, 'title' | 'description' | 'price' | 'stock' | 'tags'>>

export const PRICE_RE = /^\d{1,6}\.\d{2}$/
export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
