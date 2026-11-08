/** "just now", "45s ago", "3m ago", "2h ago", then a date. */
export function timeAgo(when: string | number): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(when).getTime()) / 1000))
  if (s < 10) return 'just now'
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return new Date(when).toLocaleDateString()
}
