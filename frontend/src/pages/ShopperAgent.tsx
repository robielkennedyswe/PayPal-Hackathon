// Screen 4: built-in shopper agent at /agent, so judges can buy without
// installing an MCP client. Chat on the left (tool chips + product, PayPal
// approval and confirmation cards), a trace of every tool call on the right.
//
// The server is stateless: it returns the whole conversation (`history`,
// Anthropic message format) each turn and we send it back next time.
// Conversations are saved in this browser (chatStore.ts) and listed in the
// Recents sidebar, like Claude or ChatGPT.

import { Fragment, useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { api } from '../api'
import { chatTitle, loadChats, newChatId, saveChats, type ChatEntry, type ChatStore } from '../chatStore'
import { Link } from '../components/Link'
import { TopBar } from '../components/TopBar'
import { timeAgo } from '../time'
import type { AgentCard, AgentCheckout, AgentHistory, AgentOrderStatus, AgentProduct, ToolCall } from '../types'

type Entry =
  | { kind: 'user'; text: string }
  | { kind: 'agent'; text: string; toolCalls: ToolCall[]; cards: AgentCard[] }
  | { kind: 'note'; text: string }

type Saved = { history: AgentHistory; entries: Entry[] }
type Chat = ChatEntry<Entry>

const EMPTY: Saved = { history: [], entries: [] }
const SUGGESTIONS = ['Find me a blue mug under $40', 'Show me something for the kitchen', 'Any vases?']
const POLL_MS = 3000
const POLL_FOR_MS = 15 * 60 * 1000 // stop polling an approval after 15 min
const APPROVED_MESSAGE = 'I approved the payment in PayPal.'

export function ShopperAgent() {
  const [store, setStore] = useState<ChatStore<Entry>>(loadChats<Entry>)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<'mock' | 'anthropic' | null>(null)
  const [openCall, setOpenCall] = useState<string | null>(null)
  const active = store.chats.find((c) => c.id === store.activeId) ?? null
  const state: Saved = active ?? EMPTY
  // Refs mirror state so send() always builds on the latest conversation,
  // even when called from a poller set up several renders ago.
  const stateRef = useRef(state)
  const activeIdRef = useRef(store.activeId)
  const busyRef = useRef(false)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    stateRef.current = state
    activeIdRef.current = store.activeId
    saveChats(store)
  }, [store, state])

  /** Apply a change to one conversation (by id, so a reply always lands in
   * the chat it belongs to) and bump it to the top of Recents. */
  const updateChat = useCallback((id: string, change: (c: Chat) => Partial<Chat>) => {
    setStore((s) => ({
      ...s,
      chats: s.chats.map((c) => (c.id === id ? { ...c, ...change(c), updatedAt: Date.now() } : c)),
    }))
  }, [])

  useEffect(() => {
    api.health().then((h) => setMode(h.ai_provider)).catch(() => setMode(null))
  }, [])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [state.entries.length, busy])

  /** Returns false if it didn't run (empty or the agent is still busy). */
  const send = useCallback(async (message: string, opts: { note?: string } = {}): Promise<boolean> => {
    const text = message.trim()
    if (!text || busyRef.current) return false
    busyRef.current = true
    setBusy(true)
    setError(null)
    const before = stateRef.current
    const shown: Entry = opts.note ? { kind: 'note', text: opts.note } : { kind: 'user', text }

    // First message of a new chat: create the conversation, titled by it.
    let id = activeIdRef.current
    if (!id) {
      const chatId = newChatId()
      id = chatId
      activeIdRef.current = chatId
      const chat: Chat = { id: chatId, title: chatTitle(text), updatedAt: Date.now(), history: [], entries: [shown] }
      setStore((s) => ({ chats: [chat, ...s.chats], activeId: chatId }))
    } else {
      updateChat(id, (c) => ({ entries: [...c.entries, shown] }))
    }

    try {
      const reply = await api.agentChat(before.history, text)
      updateChat(id, (c) => ({
        history: reply.history,
        entries: [
          ...c.entries,
          { kind: 'agent', text: reply.turn.text, toolCalls: reply.turn.tool_calls, cards: reply.turn.cards },
        ],
      }))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The agent could not reply')
    } finally {
      busyRef.current = false
      setBusy(false)
    }
    return true
  }, [updateChat])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (busy || !draft.trim()) return
    void send(draft)
    setDraft('')
  }

  // Switching is blocked while the agent is replying, so a reply can't land
  // in a conversation the user has navigated away from mid-request.
  const openChat = (id: string | null) => {
    if (busyRef.current) return
    setStore((s) => ({ ...s, activeId: id }))
    setError(null)
    setOpenCall(null)
    setDraft('')
  }

  const deleteChat = (id: string) => {
    if (busyRef.current) return
    setStore((s) => ({ chats: s.chats.filter((c) => c.id !== id), activeId: s.activeId === id ? null : s.activeId }))
    if (store.activeId === id) setOpenCall(null)
  }

  const recents = [...store.chats].sort((a, b) => b.updatedAt - a.updatedAt)

  // Orders already confirmed in the chat, so their approval cards show "Paid"
  // and stop polling.
  const confirmed = new Set(
    state.entries.flatMap((e) =>
      e.kind === 'agent' ? e.cards.flatMap((c) => (c.type === 'confirmation' ? [c.order.order_id] : [])) : [],
    ),
  )
  // Only the newest approval card polls; older ones are superseded.
  const latestApproval = [...state.entries]
    .reverse()
    .flatMap((e) => (e.kind === 'agent' ? e.cards : []))
    .find((c) => c.type === 'approval')
  const pendingOrderId =
    latestApproval?.type === 'approval' && !confirmed.has(latestApproval.checkout.order_id)
      ? latestApproval.checkout.order_id
      : null

  const onPaid = useCallback(() => {
    return send(APPROVED_MESSAGE, { note: 'PayPal approval detected. Asking the agent to confirm…' })
  }, [send])

  const allCalls = state.entries.flatMap((e) => (e.kind === 'agent' ? e.toolCalls : []))

  return (
    <>
      <TopBar />
      <main className="page agent-page">
        <header className="page-head">
          <div>
            <span className="chip agent">AI shopper agent</span>
            <h1 style={{ marginTop: 8 }}>Shop with an AI agent</h1>
            <p>
              The agent searches every published shop using the same MCP tools any AI agent can use. You approve
              the payment in PayPal; it can never pay on its own.
            </p>
          </div>
          <div className="agent-head-actions">
            {mode && (
              <span className={`mode-badge ${mode}`} title="AI_PROVIDER on the server">
                {mode === 'anthropic' ? 'Claude' : 'Mock AI (dev)'}
              </span>
            )}
          </div>
        </header>

        <div className="agent-layout">
          <aside className="card recents" aria-label="Recent chats">
            <button type="button" className="btn btn-agent btn-sm new-chat" onClick={() => openChat(null)} disabled={busy}>
              + New chat
            </button>
            <h2>Recents</h2>
            {recents.length === 0 ? (
              <p className="recents-empty">Your chats will show up here.</p>
            ) : (
              <ul className="recents-list">
                {recents.map((c) => (
                  <li key={c.id} className={c.id === store.activeId ? 'active' : ''}>
                    <button
                      type="button"
                      className="recent-open"
                      onClick={() => openChat(c.id)}
                      disabled={busy}
                      aria-current={c.id === store.activeId ? 'true' : undefined}
                    >
                      <span className="recent-title">{c.title}</span>
                      <span className="recent-time">{timeAgo(c.updatedAt)}</span>
                    </button>
                    <button
                      type="button"
                      className="recent-delete"
                      onClick={() => deleteChat(c.id)}
                      disabled={busy}
                      aria-label={`Delete chat: ${c.title}`}
                      title="Delete chat"
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <p className="recents-note">Saved in this browser only.</p>
          </aside>

          <section className="card chat" aria-label="Chat with the shopper agent">
            <div className="chat-log" aria-live="polite">
              {state.entries.length === 0 && (
                <div className="chat-empty">
                  <p className="muted">Tell the agent what you're looking for. Try:</p>
                  <div className="suggestions">
                    {SUGGESTIONS.map((s) => (
                      <button key={s} type="button" className="suggestion" onClick={() => void send(s)} disabled={busy}>
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {state.entries.map((e, i) => {
                if (e.kind === 'user')
                  return (
                    <div key={i} className="msg user">
                      <div className="bubble">{e.text}</div>
                    </div>
                  )
                if (e.kind === 'note')
                  return (
                    <p key={i} className="msg-note">
                      {e.text}
                    </p>
                  )
                return (
                  <div key={i} className="msg agent">
                    {e.toolCalls.length > 0 && (
                      <div className="tool-chips">
                        {e.toolCalls.map((c) => (
                          <button
                            key={c.id}
                            type="button"
                            className={`tool-chip${c.is_error ? ' error' : ''}`}
                            onClick={() => setOpenCall(c.id)}
                            title="Show in the trace"
                          >
                            <span aria-hidden="true">⚙</span> {c.name}
                          </button>
                        ))}
                      </div>
                    )}
                    <div className="bubble">{renderText(e.text)}</div>
                    {e.cards.map((c, j) => (
                      <CardView
                        key={j}
                        card={c}
                        busy={busy}
                        paid={c.type === 'approval' && confirmed.has(c.checkout.order_id)}
                        polling={c.type === 'approval' && c.checkout.order_id === pendingOrderId}
                        onBuy={() => void send('Yes, buy it')}
                        onCheck={() => void send(APPROVED_MESSAGE)}
                        onPaid={onPaid}
                      />
                    ))}
                  </div>
                )
              })}

              {busy && (
                <div className="msg agent">
                  <div className="bubble typing" aria-label="Agent is working">
                    <span />
                    <span />
                    <span />
                  </div>
                </div>
              )}
              {error && <div className="banner banner-error">{error}</div>}
              <div ref={endRef} />
            </div>

            <form className="chat-input" onSubmit={submit}>
              <input
                className="input"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Ask for a product, e.g. “a green bowl under $50”"
                maxLength={1000}
                aria-label="Message the shopper agent"
              />
              <button type="submit" className="btn btn-agent" disabled={busy || !draft.trim()}>
                Send
              </button>
            </form>
          </section>

          <Trace calls={allCalls} openId={openCall} onToggle={(id) => setOpenCall((o) => (o === id ? null : id))} />
        </div>
      </main>
    </>
  )
}

// ---------- cards ----------

type CardProps = {
  card: AgentCard
  busy: boolean
  paid: boolean
  polling: boolean
  onBuy: () => void
  onCheck: () => void
  onPaid: () => Promise<boolean>
}

function CardView({ card, ...props }: CardProps) {
  if (card.type === 'product') return <ProductCard product={card.product} imageUrl={card.image_url} {...props} />
  if (card.type === 'approval') return <ApprovalCard checkout={card.checkout} {...props} />
  return <ConfirmationCard order={card.order} />
}

function ProductCard({ product: p, imageUrl, busy, onBuy }: { product: AgentProduct; imageUrl: string | null } & Omit<CardProps, 'card'>) {
  return (
    <article className="agent-card product-card">
      <div className="product-card-img">{imageUrl && <img src={imageUrl} alt={p.title} />}</div>
      <div className="product-card-body">
        <h3>{p.title}</h3>
        <p className="muted product-card-shop">
          from <Link href={`/s/${p.shop.slug}`}>{p.shop.name}</Link>
        </p>
        <div className="store-meta">
          <span className="draft-price">${p.price.value}</span>
          <span className={`stock-note${p.stock <= 2 ? ' low' : ''}`}>
            {p.available ? `${p.stock} in stock` : 'Out of stock'}
          </span>
        </div>
        {p.available && (
          <button type="button" className="btn btn-agent btn-sm" onClick={onBuy} disabled={busy}>
            Buy this
          </button>
        )}
      </div>
    </article>
  )
}

function ApprovalCard({
  checkout: c,
  busy,
  paid,
  polling,
  onCheck,
  onPaid,
}: { checkout: AgentCheckout } & Omit<CardProps, 'card'>) {
  usePaidPoller(polling ? c.order_id : null, onPaid)
  return (
    <article className={`agent-card approval-card${paid ? ' paid' : ''}`}>
      <div className="approval-head">
        <span className="approval-label">PayPal checkout</span>
        <span className={`status-pill ${paid ? 'ok' : 'wait'}`}>{paid ? 'Paid' : 'Waiting for your approval'}</span>
      </div>
      <div className="approval-line">
        <span>
          {c.qty} × {c.title}
        </span>
        <strong>
          ${c.amount} {c.currency}
        </strong>
      </div>
      {!paid && (
        <>
          <a className="btn btn-paypal" href={c.approve_url} target="_blank" rel="noopener noreferrer">
            Review &amp; pay in PayPal ↗
          </a>
          <p className="approval-note">
            Sandbox test payment: open the link in a private/incognito window and log in with a PayPal sandbox
            Personal account. This page notices the approval automatically.
          </p>
          <button type="button" className="btn btn-sm" onClick={onCheck} disabled={busy}>
            I've approved, check payment
          </button>
        </>
      )}
      <p className="mono approval-id">{c.order_id}</p>
    </article>
  )
}

/** While an approval is open, poll the order and fire onPaid once it's captured. */
function usePaidPoller(orderId: string | null, onPaid: () => Promise<boolean>) {
  // Latest callback without restarting the interval when it changes.
  const onPaidRef = useRef(onPaid)
  useEffect(() => {
    onPaidRef.current = onPaid
  }, [onPaid])
  useEffect(() => {
    if (!orderId) return
    const stopAt = Date.now() + POLL_FOR_MS
    let done = false
    const timer = window.setInterval(async () => {
      if (done || document.hidden) return // skip while the tab is in the background
      if (Date.now() > stopAt) return window.clearInterval(timer)
      try {
        const order = await api.getOrder(orderId)
        // If the agent is mid-reply, onPaid returns false: retry next tick.
        if (order.status === 'COMPLETED' && !done && (await onPaidRef.current())) {
          done = true
          window.clearInterval(timer)
        }
      } catch {
        /* transient: try again next tick */
      }
    }, POLL_MS)
    return () => {
      done = true
      window.clearInterval(timer)
    }
  }, [orderId])
}

function ConfirmationCard({ order: o }: { order: AgentOrderStatus }) {
  return (
    <article className="agent-card confirm-card">
      <span className="result-icon ok" aria-hidden="true">
        ✓
      </span>
      <div>
        <h3>Payment complete</h3>
        <p className="muted">
          {o.qty} × {o.title} · ${o.amount.value} {o.amount.currency} paid via PayPal
        </p>
        <p className="mono approval-id">{o.order_id}</p>
      </div>
    </article>
  )
}

// ---------- trace panel ----------

function Trace({ calls, openId, onToggle }: { calls: ToolCall[]; openId: string | null; onToggle: (id: string) => void }) {
  const openRef = useRef<HTMLLIElement>(null)
  useEffect(() => {
    openRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [openId])

  return (
    <aside className="agent-panel trace" aria-label="Tool call trace">
      <div className="agent-panel-head">
        <span className="chip agent">MCP tool calls</span>
        <h2>What the agent did</h2>
        <p>Every call the agent made, with its exact input and output. Click one to expand it.</p>
      </div>
      {calls.length === 0 ? (
        <p className="trace-empty">No tool calls yet.</p>
      ) : (
        <ol className="trace-list">
          {calls.map((c, i) => {
            const open = c.id === openId
            return (
              <li key={c.id} ref={open ? openRef : undefined} className={open ? 'open' : ''}>
                <button type="button" className="trace-row" onClick={() => onToggle(c.id)} aria-expanded={open}>
                  <span className="trace-num">{i + 1}</span>
                  <span className="trace-name">{c.name}</span>
                  <span className={`trace-status ${c.is_error ? 'err' : 'ok'}`}>{c.is_error ? 'error' : 'ok'}</span>
                  <span className="trace-ms">{c.duration_ms} ms</span>
                </button>
                <p className="trace-input">{summarize(c.input)}</p>
                {open && (
                  <div className="trace-detail">
                    <h4>input</h4>
                    <pre>{JSON.stringify(c.input, null, 2)}</pre>
                    <h4>output</h4>
                    <pre>{JSON.stringify(c.output, null, 2)}</pre>
                  </div>
                )}
              </li>
            )
          })}
        </ol>
      )}
    </aside>
  )
}

const summarize = (input: Record<string, unknown>) =>
  Object.entries(input)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(', ') || '(no arguments)'

// ---------- tiny text renderer ----------

/** Paragraphs, "- " bullet lists and **bold**. Builds React elements (no
 * innerHTML), so agent text can never inject markup. */
function renderText(text: string): ReactNode {
  return text.split(/\n{2,}/).map((block, i) => {
    const lines = block.split('\n')
    if (lines.every((l) => l.startsWith('- ')))
      return (
        <ul key={i}>
          {lines.map((l, j) => (
            <li key={j}>{bold(l.slice(2))}</li>
          ))}
        </ul>
      )
    const head = lines.filter((l) => !l.startsWith('- '))
    const items = lines.filter((l) => l.startsWith('- '))
    return (
      <Fragment key={i}>
        <p>{bold(head.join(' '))}</p>
        {items.length > 0 && (
          <ul>
            {items.map((l, j) => (
              <li key={j}>{bold(l.slice(2))}</li>
            ))}
          </ul>
        )}
      </Fragment>
    )
  })
}

function bold(s: string): ReactNode {
  return s.split(/(\*\*[^*]+\*\*)/).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : part,
  )
}
