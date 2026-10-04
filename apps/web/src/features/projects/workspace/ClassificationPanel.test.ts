import { describe, expect, it } from 'vitest'
import type { Classification } from '@/api/graph'
import { shareOf } from './ClassificationPanel'

describe('classification share', () => {
  const data: Classification = { counts: { business: 121, control_flow: 139, infrastructure: 23 }, statements: [] }

  it('is the percentage of the statements of each class', () => {
    expect(shareOf(data, 'business')).toBe(43)
    expect(shareOf(data, 'control_flow')).toBe(49)
    expect(shareOf(data, 'infrastructure')).toBe(8)
  })

  it('is zero without statements', () => {
    expect(shareOf({ counts: {}, statements: [] }, 'business')).toBe(0)
  })
})
