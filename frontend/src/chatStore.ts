// Shopper-agent conversations, saved in this browser (localStorage) for the
// Recents sidebar. Kept client-side on purpose: there are no logins, so a
// server couldn't tell whose chats are whose, and visitors never see each
// other's conversations. Storage can throw or fill up; the chat keeps
// working either way.

import type { AgentHistory } from './types'

export type ChatEntry<E> = {
  id: string
  title: string
  updatedAt: number
  history: AgentHistory // Anthropic-format messages, sent back to the server each turn
  entries: E[] // what the UI renders
}

export type ChatStore<E> = { chats: ChatEntry<E>[]; activeId: string | null }

const KEY = 'shopmcp.agent.chats.v1'
const MAX_CHATS = 20

export function loadChats<E>(): ChatStore<E> {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? 'null') as ChatStore<E> | null
    if (parsed && Array.isArray(parsed.chats)) return { chats: parsed.chats, activeId: parsed.activeId ?? null }
  } catch {
    /* corrupted or blocked: start fresh */
  }
  return { chats: [], activeId: null }
}

/** Saves the newest MAX_CHATS chats; if storage is full, drops the oldest until it fits. */
export function saveChats<E>(store: ChatStore<E>) {
  let chats = [...store.chats].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_CHATS)
  while (true) {
    try {
      localStorage.setItem(KEY, JSON.stringify({ chats, activeId: store.activeId }))
      return
    } catch {
      if (chats.length <= 1) return // can't persist at all; the in-memory chat still works
      chats = chats.slice(0, -1)
    }
  }
}

export function newChatId(): string {
  // randomUUID needs a secure context (https or localhost); fall back otherwise.
  return typeof crypto?.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

export function chatTitle(firstMessage: string): string {
  const t = firstMessage.trim().replace(/\s+/g, ' ')
  return t.length > 42 ? `${t.slice(0, 41)}…` : t || 'New chat'
}
