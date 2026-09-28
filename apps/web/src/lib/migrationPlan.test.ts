import { describe, expect, it } from 'vitest'
import { moveStory, planDiff, suggestPlan, validatePlan, type PlanStory } from './migrationPlan'

const s = (
  id: string,
  deps: [string, 'hard' | 'soft'][] = [],
  priority: PlanStory['priority'] = 'P0',
  points = 3,
): PlanStory => ({
  id,
  priority,
  points,
  dependsOn: deps.map(([story, kind]) => ({ story, kind, reason: '' })),
})

const stories = [
  s('A'),
  s('B', [['A', 'hard']]),
  s('C', [['A', 'hard']], 'P1'),
  s('D', [
    ['B', 'hard'],
    ['C', 'soft'],
  ]),
]

describe('migration plan', () => {
  it('suggests waves that respect every dependency', () => {
    const plan = suggestPlan(stories)
    expect(plan).toEqual([['A'], ['B', 'C'], ['D']])
    expect(validatePlan(plan, stories)).toEqual([])
  })

  it('rejects a move that puts a story before a hard dependency', () => {
    const plan = suggestPlan(stories)
    expect(moveStory(plan, stories, 'B', 0).accepted).toBe(true) // same wave as its dependency is fine
    const r = moveStory(plan, stories, 'D', 0)
    expect(r.accepted).toBe(false)
    expect(r.plan).toBe(plan)
    expect(r.newIssues[0]).toMatchObject({ story: 'D', dependency: 'B', kind: 'hard' })
  })

  it('accepts a move over a soft dependency with a warning', () => {
    const plan = suggestPlan(stories)
    const r = moveStory(plan, stories, 'C', 3)
    expect(r.accepted).toBe(true)
    expect(r.plan).toEqual([['A'], ['B'], ['D'], ['C']])
    expect(r.newIssues).toEqual([
      expect.objectContaining({ story: 'D', dependency: 'C', kind: 'soft', problem: 'before' }),
    ])
  })

  it('reports dependencies that are not in the plan and the difference from the suggestion', () => {
    const plan = [['A'], ['C'], ['D']]
    expect(validatePlan(plan, stories)).toEqual([
      expect.objectContaining({ story: 'D', dependency: 'B', problem: 'missing' }),
    ])
    expect(planDiff(suggestPlan(stories), [['A', 'C'], ['B'], ['D']])).toEqual([{ story: 'C', from: 1, to: 0 }])
  })
})
