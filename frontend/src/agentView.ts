// The listing exactly as AI agents receive it from the MCP `get_product`
// tool. Shown live on the review screen so sellers see what agents see.
// backend/app/tools.py get_product returns this same shape (a test checks the keys).

import type { Product, Shop } from './types'

export type ListingFields = Pick<Product, 'title' | 'description' | 'price' | 'stock' | 'tags' | 'attributes' | 'image_url'>

// Agents get full links; on the hosted site the backend and frontend share this origin.
const absolute = (path: string) => new URL(path, window.location.origin).href

export function agentView(productId: string, fields: ListingFields, shop: Pick<Shop, 'name' | 'slug'>) {
  return {
    id: productId,
    title: fields.title,
    description: fields.description,
    price: { value: fields.price, currency: 'USD' },
    shipping_and_tax: 'Included: the PayPal total is price × quantity, with no shipping or tax added.',
    stock: fields.stock,
    available: fields.stock > 0,
    attributes: fields.attributes,
    tags: fields.tags,
    image_url: fields.image_url ? absolute(fields.image_url) : null,
    shop: { name: shop.name, slug: shop.slug, url: absolute(`/s/${shop.slug}`) },
    checkout: 'Call create_checkout; the buyer approves payment in PayPal.',
  }
}
