import { describe, expect, it } from 'vitest'
import type { DeltaOut } from '@/api/delta'
import { baselineOf, designOf, endpointOf, impactOf, isDeltaEmpty } from './model'

describe('baseline', () => {
  it('reads the passing tests and the ones already failing before the delta', () => {
    expect(baselineOf({ passed: ['LoanTest.creates', 'LoanTest.rejects'], failed: ['RateTest.flaky'] })).toEqual({
      passed: ['LoanTest.creates', 'LoanTest.rejects'],
      failed: ['RateTest.flaky'],
    })
  })

  it('is null before the baseline and tolerates missing or malformed lists', () => {
    expect(baselineOf(null)).toBeNull()
    expect(baselineOf({ passed: ['A.ok', ''] })).toEqual({ passed: ['A.ok'], failed: [] })
  })
})

describe('delta design', () => {
  it('reads the changes with their stories, endpoint, reuses, tables and files, and the decisions', () => {
    const design = designOf({
      changes: [
        {
          name: 'Rate quote',
          description: 'Quote the rate of a loan',
          stories: ['US-001'],
          http_method: 'get',
          path: '/loans/{id}/rate',
          request: [{ name: 'id', type: 'Long' }],
          response: [{ name: 'rate', type: 'BigDecimal' }],
          reuses: ['LoanRepository'],
          tables: ['LOAN'],
          new_tables: ['RATE'],
          files: ['src/main/java/demo/RateController.java'],
        },
      ],
      decisions: [{ title: 'Reuse the loan repository', decision: 'The rate reads the loan through it.' }],
    })
    expect(design).toEqual({
      changes: [
        {
          name: 'Rate quote',
          description: 'Quote the rate of a loan',
          stories: ['US-001'],
          endpoint: 'GET /loans/{id}/rate',
          request: [{ name: 'id', type: 'Long' }],
          response: [{ name: 'rate', type: 'BigDecimal' }],
          reuses: ['LoanRepository'],
          tables: ['LOAN'],
          newTables: ['RATE'],
          files: ['src/main/java/demo/RateController.java'],
        },
      ],
      decisions: [{ title: 'Reuse the loan repository', decision: 'The rate reads the loan through it.' }],
    })
  })

  it('is null without a design and tolerates a change without endpoint or lists', () => {
    expect(designOf(null)).toBeNull()
    expect(designOf({ changes: [{ name: 'Audit' }], decisions: 'x' })).toEqual({
      changes: [
        {
          name: 'Audit',
          description: '',
          stories: [],
          endpoint: null,
          request: [],
          response: [],
          reuses: [],
          tables: [],
          newTables: [],
          files: [],
        },
      ],
      decisions: [],
    })
    expect(endpointOf(undefined, '/rates')).toBe('/rates')
    expect(endpointOf('post', '')).toBeNull()
  })
})

describe('empty delta', () => {
  const empty: DeltaOut = { inventory: null, baseline: null, design: null, added: [], changed: [], report: null }

  it('is empty only when nothing was produced', () => {
    expect(isDeltaEmpty(empty)).toBe(true)
    expect(isDeltaEmpty({ ...empty, inventory: { stack: 'spring-boot' } })).toBe(false)
    expect(isDeltaEmpty({ ...empty, added: ['a.java'] })).toBe(false)
    expect(isDeltaEmpty({ ...empty, report: '# DELTA' })).toBe(false)
  })
})

describe('impact', () => {
  it('reads what the delta reaches and what nobody observed; null before the validation', () => {
    expect(
      impactOf({
        changed: ['a/PaymentController.java'],
        affected: ['a/PaymentController.java', 'a/PaymentService.java'],
        outside: ['a/PaymentService.java'],
        unobserved: ['a/PaymentService.java'],
        tables: ['orders'],
        transactions: ['a/PaymentController.java'],
      }),
    ).toEqual({
      affected: ['a/PaymentController.java', 'a/PaymentService.java'],
      outside: ['a/PaymentService.java'],
      unobserved: ['a/PaymentService.java'],
      tables: ['orders'],
      transactions: ['a/PaymentController.java'],
    })
    expect(impactOf(null)).toBeNull()
    expect(impactOf({ tables: 'x' })).toEqual({ affected: [], outside: [], unobserved: [], tables: [], transactions: [] })
  })
})

