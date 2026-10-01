import { describe, expect, it } from 'vitest'
import type { Notification } from '@/api/topbar'
import { isUnread, matches } from './topbarModel'

const at = (occurredAt: string): Notification => ({
  id: 'n',
  kind: 'verdict',
  title: 'PayOrder · PROVEN',
  projectId: null,
  projectName: null,
  tab: null,
  occurredAt,
})

describe('top bar model', () => {
  it('counts as unread what happened after the last read', () => {
    expect(isUnread(at('2026-09-30T10:00:00Z'), null)).toBe(true)
    expect(isUnread(at('2026-09-30T10:00:00Z'), '2026-09-30T09:00:00Z')).toBe(true)
    expect(isUnread(at('2026-09-30T08:00:00Z'), '2026-09-30T09:00:00Z')).toBe(false)
  })

  it('matches two or more characters in any value, ignoring case', () => {
    expect(matches('arch', 'Software Architect', null)).toBe(true)
    expect(matches('a', 'Architect')).toBe(false)
    expect(matches('zz', 'Architect', undefined)).toBe(false)
  })
})
