// Where PayPal's return/cancel redirect lands (via the backend), e.g.
// /checkout/result?status=completed&order=ord_123

import { useEffect, useState } from 'react'
import { TopBar } from '../components/TopBar'

type Order = { id: string; amount: string; status: string; paypal_capture_id: string | null }

const MESSAGES: Record<string, { title: string; text: string; ok: boolean }> = {
  completed: { title: 'Payment complete', text: 'Thanks! The seller has been notified and your order is confirmed.', ok: true },
  cancelled: { title: 'Payment cancelled', text: 'No money was taken. You can ask the agent to try again.', ok: false },
  out_of_stock: { title: 'Sold out', text: 'This item sold out before checkout finished. You were not charged.', ok: false },
  failed: { title: 'Payment failed', text: 'PayPal could not complete the payment. You were not charged.', ok: false },
  not_found: { title: 'Order not found', text: "We couldn't find this order.", ok: false },
  unconfirmed: {
    title: "We couldn't confirm this payment",
    text: 'Ask your AI agent for the order status; it checks with PayPal directly.',
    ok: false,
  },
}
const CHECKING = { title: 'Confirming your payment…', text: 'Checking the order with the shop.', ok: true }

export function CheckoutResult({ search }: { search: string }) {
  const params = new URLSearchParams(search)
  const status = params.get('status') ?? 'not_found'
  const orderId = params.get('order')
  // undefined = still loading, null = not found / failed
  const [order, setOrder] = useState<Order | null | undefined>(orderId ? undefined : null)

  useEffect(() => {
    if (!orderId) return
    fetch(`/api/orders/${encodeURIComponent(orderId)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setOrder)
      .catch(() => setOrder(null))
  }, [orderId])

  // The URL's status is only a hint (anyone can type ?status=completed):
  // "Payment complete" needs the server to say the order is COMPLETED.
  let msg = MESSAGES[status] ?? MESSAGES.not_found
  if (status === 'completed') {
    if (order === undefined) msg = CHECKING
    else if (order?.status !== 'COMPLETED') msg = order ? MESSAGES.unconfirmed : MESSAGES.not_found
  }

  return (
    <>
      <TopBar />
      <main className="page">
        <section className="card card-pad result-card">
          <span className={`result-icon ${msg.ok ? 'ok' : 'bad'}`} aria-hidden="true">
            {msg === CHECKING ? '…' : msg.ok ? '✓' : '!'}
          </span>
          <h1>{msg.title}</h1>
          <p className="muted">{msg.text}</p>
          {order && (
            <dl className="result-details">
              <dt>Order</dt>
              <dd className="mono">{order.id}</dd>
              <dt>Amount</dt>
              <dd>${order.amount} USD</dd>
              {order.paypal_capture_id && (
                <>
                  <dt>PayPal capture</dt>
                  <dd className="mono">{order.paypal_capture_id}</dd>
                </>
              )}
            </dl>
          )}
          <p className="muted" style={{ fontSize: 13 }}>
            You can close this tab and return to your AI agent.
          </p>
        </section>
      </main>
    </>
  )
}
