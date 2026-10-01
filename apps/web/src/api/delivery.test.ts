import { describe, expect, it } from 'vitest'
import { severityCounts } from './delivery'

describe('hardening counts', () => {
  it('lists the severities with findings, most severe first', () => {
    expect(severityCounts({ counts: { low: 2, critical: 1, medium: 0 } })).toEqual([
      { severity: 'critical', count: 1 },
      { severity: 'low', count: 2 },
    ])
    expect(severityCounts({ counts: {} })).toEqual([])
  })
})
