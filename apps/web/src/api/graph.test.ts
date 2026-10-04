import { describe, expect, it } from 'vitest'
import { EMPTY_INSIGHTS, normalizeInsights } from './graph'

describe('graph insights', () => {
  it('are empty for a missing or malformed body', () => {
    expect(normalizeInsights(undefined)).toEqual(EMPTY_INSIGHTS)
    expect(normalizeInsights('nope')).toEqual(EMPTY_INSIGHTS)
    expect(normalizeInsights({})).toEqual(EMPTY_INSIGHTS)
  })

  it('keep descriptions, observations and well-formed scenarios', () => {
    const insights = normalizeInsights({
      descriptions: { sp: 'Pays the bill.', blank: ' ', bad: 3 },
      observations: ['Large procedure', 7],
      scenarios: [
        {
          id: 's1',
          name: 'Late payment',
          persona: 'Teller',
          summary: 'A teller pays a late bill.',
          rules: ['BR-1'],
          steps: [{ title: 'Validate', nodes: ['sp.b1'], rule: 'BR-1' }, { nodes: ['sp.b2'] }],
        },
        { name: 'no id' },
      ],
    })
    expect(insights.descriptions).toEqual({ sp: 'Pays the bill.' })
    expect(insights.observations).toEqual(['Large procedure'])
    expect(insights.scenarios).toEqual([
      {
        id: 's1',
        name: 'Late payment',
        persona: 'Teller',
        summary: 'A teller pays a late bill.',
        rules: ['BR-1'],
        steps: [
          { title: 'Validate', nodes: ['sp.b1'], rule: 'BR-1' },
          { title: '', nodes: ['sp.b2'], rule: null },
        ],
      },
    ])
  })
})
