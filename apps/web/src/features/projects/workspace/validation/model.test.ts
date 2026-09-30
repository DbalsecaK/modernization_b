import { describe, expect, it } from 'vitest'
import type { TraceRule, VerdictOut } from '@/api/validation'
import {
  allChecks,
  byModule,
  checkStatusKey,
  checkTitleKey,
  checkTone,
  differencesOf,
  excerptLines,
  excerptRange,
  filterRules,
  passedCount,
  stateCounts,
  toVerdict,
  traceState,
} from './model'

function verdict(id: string, module: string, createdAt: string, extra: Partial<VerdictOut> = {}): VerdictOut {
  return {
    id,
    runId: `run-${id}`,
    module,
    verdict: 'PARTLY PROVEN',
    checks: [],
    notProven: [],
    hasProofPack: true,
    createdAt,
    ...extra,
  }
}

function rule(key: string, verified: boolean | null, extra: Partial<TraceRule> = {}): TraceRule {
  return {
    key,
    name: `Rule ${key}`,
    priority: 'P1',
    status: 'review',
    sources: ['sp_pago_orden.sp:40-42'],
    targetFiles: [],
    cases: 0,
    matched: 0,
    verified,
    ...extra,
  }
}

describe('checks', () => {
  it('orders the six checks and adds the ones not reported as not checked', () => {
    const checks = allChecks([
      { key: 'same_behaviour', title: 'Same behaviour', status: 'passed', detail: '1 golden case(s) reproduced' },
      { key: 'tests_ran', title: 'Tests ran', status: 'passed', detail: '7 test(s) passed' },
      { key: 'extra_check', title: 'Extra', status: 'failed', detail: 'x' },
    ])
    expect(checks.map((c) => c.key)).toEqual([
      'tests_ran',
      'rules_traced',
      'same_behaviour',
      'fresh_inputs',
      'canary',
      'source_intact',
      'extra_check',
    ])
    expect(checks[0]).toMatchObject({ status: 'passed', missing: false, detail: '7 test(s) passed' })
    expect(checks[1]).toMatchObject({ status: 'not_checked', missing: true })
    expect(checks.filter((c) => c.missing)).toHaveLength(4)
  })

  it('maps keys and statuses to i18n keys and tones', () => {
    expect(checkTitleKey('same_behaviour')).toBe('validation.checkTitles.sameBehaviour')
    expect(checkStatusKey('not_checked')).toBe('validation.status.notChecked')
    expect(['passed', 'failed', 'not_checked'].map((s) => checkTone(s as 'passed'))).toEqual([
      'good',
      'critical',
      'warning',
    ])
  })

  it('maps the API verdict to the badge value', () => {
    expect(['PROVEN', 'PARTLY PROVEN', 'NOT PROVEN', null, 'other'].map(toVerdict)).toEqual([
      'PROVEN',
      'PARTLY_PROVEN',
      'NOT_PROVEN',
      'NOT_VERIFIED',
      'NOT_VERIFIED',
    ])
  })
})

describe('byModule', () => {
  it('keeps the newest verdict of each module prominent and the rest as history', () => {
    const groups = byModule([
      verdict('a1', 'PayOrder', '2026-09-28T10:00:00Z'),
      verdict('b1', 'Refund', '2026-09-29T09:00:00Z'),
      verdict('a2', 'PayOrder', '2026-09-29T10:00:00Z'),
      verdict('a0', 'PayOrder', '2026-09-27T10:00:00Z'),
    ])
    expect(groups.map((g) => [g.module, g.latest.id, g.history.map((v) => v.id)])).toEqual([
      ['PayOrder', 'a2', ['a1', 'a0']],
      ['Refund', 'b1', []],
    ])
    expect(byModule([])).toEqual([])
  })

  it('counts the checks that passed', () => {
    const v = verdict('a', 'M', '2026-09-29T10:00:00Z', {
      checks: [
        { key: 'tests_ran', title: '', status: 'passed', detail: '' },
        { key: 'canary', title: '', status: 'failed', detail: '' },
      ],
    })
    expect(passedCount(v)).toBe(1)
  })
})

describe('traceability', () => {
  const rules = [
    rule('RULE-001', true, { targetFiles: ['src/main/java/demo/PayOrderService.java'], cases: 1, matched: 1 }),
    rule('RULE-002', null, { name: 'Amount must match' }),
    rule('RULE-003', false),
  ]

  it('knows the verification state of a rule', () => {
    expect([true, false, null, undefined].map(traceState)).toEqual(['verified', 'notVerified', 'pending', 'pending'])
    expect(stateCounts(rules)).toEqual({ verified: 1, notVerified: 1, pending: 1 })
  })

  it('filters by state and by text over key, name, sources and target files', () => {
    expect(filterRules(rules, 'all', '').map((r) => r.key)).toEqual(['RULE-001', 'RULE-002', 'RULE-003'])
    expect(filterRules(rules, 'pending', '').map((r) => r.key)).toEqual(['RULE-002'])
    expect(filterRules(rules, 'all', ' amount ').map((r) => r.key)).toEqual(['RULE-002'])
    expect(filterRules(rules, 'all', 'PayOrderService').map((r) => r.key)).toEqual(['RULE-001'])
    expect(filterRules(rules, 'verified', 'amount')).toEqual([])
  })

  it('numbers the excerpt lines from the first line and marks the highlighted ones', () => {
    const excerpt = {
      path: 'sp/sp_pago_orden.sp',
      firstLine: 37,
      lines: ['a', 'b', 'c', 'd'],
      highlighted: [38, 39, 99],
      truncated: false,
    }
    expect(excerptLines(excerpt)).toEqual([
      { number: 37, text: 'a', highlighted: false },
      { number: 38, text: 'b', highlighted: true },
      { number: 39, text: 'c', highlighted: true },
      { number: 40, text: 'd', highlighted: false },
    ])
    expect(excerptRange(excerpt)).toBe('sp/sp_pago_orden.sp:37-40')
    expect(excerptRange({ ...excerpt, lines: ['a'] })).toBe('sp/sp_pago_orden.sp:37')
  })

  it('reads the differences of a case defensively', () => {
    expect(
      differencesOf({
        differences: [
          { path: 'outputs:@total', expected: '10.50', actual: '10.5' },
          { path: 'returns', expected: 0, actual: null },
          { expected: 'x' },
        ],
      } as unknown as Parameters<typeof differencesOf>[0]),
    ).toEqual([
      { path: 'outputs:@total', expected: '10.50', actual: '10.5' },
      { path: 'returns', expected: '0', actual: null },
      { path: '', expected: 'x', actual: null },
    ])
  })
})

describe('frontend verdicts', () => {
  it('complete the frontend checks, not the backend ones', () => {
    const checks = allChecks([{ key: 'compiles', title: 'Compiles', status: 'passed', detail: 'ok' }], 'frontend-react')
    expect(checks.map((c) => c.key)).toEqual([
      'compiles',
      'screens_mount',
      'fields_covered',
      'validations',
      'actions',
      'accessibility',
    ])
    expect(checks.filter((c) => c.missing)).toHaveLength(5)
  })
})
