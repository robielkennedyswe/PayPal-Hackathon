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

// ---- shopper agent (POST /api/agent/chat; backend/app/agent.py) ----

/** Listing exactly as agents see it (get_product; same shape as agentView.ts). */
export type AgentProduct = {
  id: string
  title: string
  description: string
  price: { value: string; currency: string }
  stock: number
  available: boolean
  attributes: Record<string, string | number | boolean>
  tags: string[]
  shop: { name: string; slug: string }
}

export type AgentCheckout = {
  order_id: string
  approve_url: string
  amount: string
  currency: string
  product_id: string
  title: string
  qty: number
  status: string
}

export type AgentOrderStatus = {
  order_id: string
  status: 'CREATED' | 'APPROVED' | 'COMPLETED'
  message: string
  title: string | null
  qty: number
  amount: { value: string; currency: string }
}

export type ToolCall = {
  id: string
  name: string
  input: Record<string, unknown>
  output: unknown
  is_error: boolean
  duration_ms: number
}

export type AgentCard =
  | { type: 'product'; product: AgentProduct; image_url: string | null }
  | { type: 'approval'; checkout: AgentCheckout }
  | { type: 'confirmation'; order: AgentOrderStatus }

export type AgentTurn = { text: string; tool_calls: ToolCall[]; cards: AgentCard[] }

/** Anthropic-format messages. Opaque to the UI: stored and sent back as-is. */
export type AgentHistory = unknown[]

export type AgentReply = { history: AgentHistory; turn: AgentTurn }
