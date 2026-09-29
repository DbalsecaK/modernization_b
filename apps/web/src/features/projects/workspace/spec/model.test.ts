import { describe, expect, it } from 'vitest'
import type { PlanProblem, RuleOut, StoryOut } from '@/api/spec'
import {
  camelKey,
  citation,
  dependenciesOf,
  dependentsOf,
  gherkinProblemsOf,
  groupByFeature,
  isActive,
  moveInWaves,
  newProblems,
  orphanLinks,
  planProblemsOf,
  problemsByCriterion,
  sameWaves,
  toRuleView,
  waveIndex,
} from './model'

function rule(data: Record<string, unknown>): RuleOut {
  return { key: 'RULE-001', version: 2, status: 'review', data, origin: 'extracted', createdAt: '2026-09-29T10:00:00Z' }
}

function story(key: string, extra: Partial<StoryOut> = {}): StoryOut {
  return {
    key,
    version: 1,
    feature: '',
    title: `Story ${key}`,
    narrative: '',
    criteria: [],
    links: [],
    priority: 'P1',
    estimate: 3,
    status: 'review',
    origin: 'extracted',
    outOfScope: false,
    mergedInto: null,
    reason: null,
    action: 'create',
    createdBy: null,
    createdByName: null,
    createdAt: '2026-09-29T10:00:00Z',
    traced: false,
    dependsOn: [],
    ...extra,
  }
}

describe('toRuleView', () => {
  it('maps the snake_case rule card of the worker', () => {
    const view = toRuleView(
      rule({
        id: 'RULE-001',
        name: 'Order must be pending',
        domain: 'payments',
        category: 'validation',
        priority: 'P0',
        statement: 'Only a pending order can be paid.',
        scenarios: ['Scenario: Pay\n  Given a pending order\n  When it is paid\n  Then it is marked A'],
        inputs: [{ name: 'order_id', type: 'integer', description: 'The order' }],
        hardcoded: ['A'],
        suspected_defect: 'The status is not checked on retries',
        confidence: 'high',
        sme_question: 'Can a cancelled order be paid?',
        sources: [
          { file: 'sp_pago_orden.sp', line_start: 40, line_end: 42 },
          { file: 'sp_pago_orden.sp', line_start: 50, line_end: 50 },
        ],
      }),
    )
    expect(view).toMatchObject({
      key: 'RULE-001',
      version: 2,
      name: 'Order must be pending',
      priority: 'P0',
      confidence: 'high',
      suspectedDefect: 'The status is not checked on retries',
      smeQuestion: 'Can a cancelled order be paid?',
      hardcoded: ['A'],
      inputs: [{ name: 'order_id', type: 'integer', description: 'The order' }],
      outputs: [],
    })
    expect(view.scenarios).toHaveLength(1)
    expect(view.sources.map(citation)).toEqual(['sp_pago_orden.sp:40-42', 'sp_pago_orden.sp:50'])
  })

  it('reads a partial or malformed card without failing', () => {
    const view = toRuleView(
      rule({ scenarios: 'not a list', sources: [{ file: 'a.sp', line_start: 7 }], sme_question: ' ' }),
    )
    expect(view.name).toBe('RULE-001')
    expect(view.priority).toBe('P1')
    expect(view.confidence).toBe('medium')
    expect(view.scenarios).toEqual([])
    expect(view.smeQuestion).toBeNull()
    expect(view.sources).toEqual([{ file: 'a.sp', lineStart: 7, lineEnd: 7 }])
  })
})

describe('stories', () => {
  it('knows which statuses are active', () => {
    expect(['draft', 'review', 'question', 'approved'].map((status) => isActive({ status }))).toEqual([
      true,
      true,
      true,
      true,
    ])
    expect(isActive({ status: 'discarded' })).toBe(false)
    expect(isActive({ status: 'merged' })).toBe(false)
  })

  it('maps dependencies and finds dependents among active stories', () => {
    const a = story('US-001')
    const b = story('US-002', {
      dependsOn: [{ on: 'US-001', strength: 'hard', reason: 'shares a table', origin: 'graph' }],
    })
    const c = story('US-003', { status: 'discarded', dependsOn: [{ on: 'US-001', strength: 'soft' }] })
    expect(dependenciesOf(b)).toEqual([{ on: 'US-001', strength: 'hard', reason: 'shares a table', origin: 'graph' }])
    expect(dependenciesOf(c)[0]).toMatchObject({ strength: 'soft', reason: '', origin: 'graph' })
    expect(dependentsOf('US-001', [a, b, c])).toEqual(['US-002'])
  })

  it('lists the links only this story covers', () => {
    const a = story('US-001', { links: ['RULE-001', 'RULE-002'] })
    const b = story('US-002', { links: ['RULE-002'] })
    const gone = story('US-003', { status: 'merged', links: ['RULE-001'] })
    expect(orphanLinks(a, [a, b, gone])).toEqual(['RULE-001'])
  })

  it('groups by feature, stories without one last', () => {
    const groups = groupByFeature([
      story('US-001'),
      story('US-002', { feature: 'Payments' }),
      story('US-003', { feature: 'Orders' }),
      story('US-004', { feature: 'Payments' }),
    ])
    expect(groups.map((g) => [g.feature, g.items.map((s) => s.key)])).toEqual([
      ['Payments', ['US-002', 'US-004']],
      ['Orders', ['US-003']],
      ['', ['US-001']],
    ])
  })
})

describe('problems', () => {
  it('turns API codes into i18n keys', () => {
    expect(camelKey('missing_given')).toBe('missingGiven')
    expect(camelKey('two_behaviours')).toBe('twoBehaviours')
    expect(camelKey('empty')).toBe('empty')
  })

  it('groups Gherkin problems by criterion', () => {
    const byIndex = problemsByCriterion([
      { criterion: 0, code: 'missing_given', line: 0, message: '' },
      { criterion: 2, code: 'free_text', line: 3, message: '' },
      { criterion: 0, code: 'missing_then', line: 0, message: '' },
    ])
    expect(byIndex.get(0)?.map((p) => p.code)).toEqual(['missing_given', 'missing_then'])
    expect(byIndex.get(1)).toBeUndefined()
    expect(byIndex.get(2)).toHaveLength(1)
  })

  it('keeps only well-formed problems of a rejected save', () => {
    const gherkin = { criterion: 0, code: 'missing_when', line: 0, message: 'x' }
    const plan = { code: 'hard_dependency', story: 'US-002', on: 'US-001', message: 'x' }
    expect(gherkinProblemsOf([gherkin, plan, null, 'x'])).toEqual([gherkin])
    expect(planProblemsOf([gherkin, plan, 3])).toEqual([plan])
  })

  it('finds the plan problems a change added', () => {
    const soft = (story: string, on: string): PlanProblem => ({ code: 'soft_dependency', story, on, message: '' })
    expect(newProblems([soft('US-003', 'US-002')], [soft('US-003', 'US-002'), soft('US-004', 'US-001')])).toEqual([
      soft('US-004', 'US-001'),
    ])
  })
})

describe('moveInWaves', () => {
  const waves = [['US-001'], ['US-002', 'US-003'], ['US-004']]

  it('moves a story to another wave, at the end or at a position', () => {
    expect(moveInWaves(waves, 'US-004', 1)).toEqual([['US-001'], ['US-002', 'US-003', 'US-004']])
    expect(moveInWaves(waves, 'US-004', 1, 0)).toEqual([['US-001'], ['US-004', 'US-002', 'US-003']])
  })

  it('reorders inside a wave', () => {
    expect(moveInWaves(waves, 'US-003', 1, 0)).toEqual([['US-001'], ['US-003', 'US-002'], ['US-004']])
  })

  it('creates a wave past the last one and drops the waves left empty', () => {
    expect(moveInWaves(waves, 'US-001', 3)).toEqual([['US-002', 'US-003'], ['US-004'], ['US-001']])
  })

  it('does not change the original and clamps the index', () => {
    const copy = JSON.parse(JSON.stringify(waves)) as string[][]
    expect(moveInWaves(waves, 'US-002', 0, 99)).toEqual([['US-001', 'US-002'], ['US-003'], ['US-004']])
    expect(waves).toEqual(copy)
  })

  it('compares plans and finds a story wave', () => {
    expect(sameWaves(waves, moveInWaves(waves, 'US-001', 0))).toBe(true)
    expect(sameWaves(waves, moveInWaves(waves, 'US-001', 1))).toBe(false)
    expect(waveIndex(waves, 'US-003')).toBe(1)
    expect(waveIndex(waves, 'US-999')).toBe(-1)
  })
})
