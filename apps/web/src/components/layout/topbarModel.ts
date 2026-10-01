import type { Notification } from '@/api/topbar'

/** Per viewer, in this browser: when the notifications were last read. A convenience; nothing depends on it. */
const seenKey = (userId: string) => `nexti.notifications.seen.${userId}`

export function readSeen(userId: string): string | null {
  try {
    return localStorage.getItem(seenKey(userId))
  } catch {
    return null
  }
}

export function writeSeen(userId: string, iso: string) {
  try {
    localStorage.setItem(seenKey(userId), iso)
  } catch {
    // Storage blocked (private window, site data cleared): the dot just stays.
  }
}

/** A notification is unread when it happened after the list was last read (or it was never read). */
export const isUnread = (n: Notification, seen: string | null) => seen == null || n.occurredAt > seen

/** Case-insensitive match of a search query in any of the values. */
export const matches = (query: string, ...values: (string | null | undefined)[]) => {
  const q = query.trim().toLowerCase()
  return q.length >= 2 && values.some((v) => (v ?? '').toLowerCase().includes(q))
}
