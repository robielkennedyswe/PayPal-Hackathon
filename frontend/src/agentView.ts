// The listing exactly as AI agents receive it from the MCP `get_product`
// tool. Shown live on the review screen so sellers see what agents see.
// Monday's backend get_product must return this same shape.

import type { Product, Shop } from './types'

export type ListingFields = Pick<Product, 'title' | 'description' | 'price' | 'stock' | 'tags' | 'attributes'>

export function agentView(productId: string, fields: ListingFields, shop: Pick<Shop, 'name' | 'slug'>) {
  return {
    id: productId,
    title: fields.title,
    description: fields.description,
    price: { value: fields.price, currency: 'USD' },
    stock: fields.stock,
    available: fields.stock > 0,
    attributes: fields.attributes,
    tags: fields.tags,
    shop: { name: shop.name, slug: shop.slug },
    checkout: 'Call create_checkout; the buyer approves payment in PayPal.',
  }
}
