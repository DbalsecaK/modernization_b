import { describe, expect, it } from 'vitest'
import { comparisonOf, fieldLabel, inventoryOf, isDirty, mappingState, similarityLabel, sourceLabel } from './model'

describe('target inventory', () => {
  it('reads the stack, the endpoints with their fields and the tables', () => {
    const inventory = inventoryOf({
      stack: 'spring-boot',
      main_class: 'com.acme.LoansApplication',
      artifact: 'loans.jar',
      schema: null,
      properties: { 'server.port': '8080' },
      slices: [{ unit: 'LoanService', file: 'src/LoanService.java', first: 1, last: 80 }],
      endpoints: [
        {
          method: 'post',
          path: '/loans',
          handler: 'LoanController.create',
          file: 'src/LoanController.java',
          line: 21,
          request: [{ name: 'amount', type: 'BigDecimal' }],
          response: [{ name: 'code', type: '' }],
        },
      ],
      tables: [{ name: 'LOAN', columns: ['ID', 'AMOUNT'], key: ['ID'] }],
    })
    expect(inventory).toEqual({
      stack: 'spring-boot',
      mainClass: 'com.acme.LoansApplication',
      artifact: 'loans.jar',
      schema: null,
      endpoints: [
        {
          method: 'POST',
          path: '/loans',
          handler: 'LoanController.create',
          file: 'src/LoanController.java',
          line: 21,
          request: [{ name: 'amount', type: 'BigDecimal' }],
          response: [{ name: 'code', type: '' }],
        },
      ],
      tables: [{ name: 'LOAN', columns: ['ID', 'AMOUNT'], key: ['ID'] }],
    })
    expect(fieldLabel(inventory!.endpoints[0].request[0])).toBe('amount: BigDecimal')
    expect(fieldLabel(inventory!.endpoints[0].response[0])).toBe('code')
    expect(sourceLabel(inventory!.endpoints[0])).toBe('src/LoanController.java:21')
  })

  it('is null before the intake and tolerates missing or malformed parts', () => {
    expect(inventoryOf(null)).toBeNull()
    expect(inventoryOf({ endpoints: 'x', tables: [{ name: 'T' }] })).toEqual({
      stack: 'unknown',
      mainClass: null,
      artifact: null,
      schema: null,
      endpoints: [],
      tables: [{ name: 'T', columns: [], key: [] }],
    })
    expect(sourceLabel({ file: 'a.java', line: null })).toBe('a.java')
  })
})

describe('rule comparison', () => {
  it('reads present, missing and extra rules', () => {
    const comparison = comparisonOf({
      present: [{ legacy: 'BR-001', name: 'Amount limit', target: 'Validate amount', similarity: 0.62 }],
      missing: [{ legacy: 'BR-002', name: 'Late fee', target: null, similarity: 0.1 }],
      extra: ['Audit trail', { name: 'Rate cache' }, 3],
    })
    expect(comparison).toEqual({
      present: [{ legacy: 'BR-001', name: 'Amount limit', target: 'Validate amount', similarity: 0.62 }],
      missing: [{ legacy: 'BR-002', name: 'Late fee', target: null, similarity: 0.1 }],
      extra: ['Audit trail', 'Rate cache'],
    })
    expect(comparisonOf(null)).toBeNull()
    expect(comparisonOf({})).toEqual({ present: [], missing: [], extra: [] })
    expect(similarityLabel(0.62)).toBe('62%')
    expect(similarityLabel(null)).toBe('')
  })
})

describe('mapping state', () => {
  it('is ready for C2 only with a mapping and no problems', () => {
    expect(mappingState({ mapping: null, problems: [] })).toBe('notTakenIn')
    expect(mappingState({ mapping: 'programs: []', problems: ['x'] })).toBe('problems')
    expect(mappingState({ mapping: 'programs: []', problems: [] })).toBe('ready')
  })

  it('knows when the editor has unsaved changes', () => {
    expect(isDirty('a', 'a')).toBe(false)
    expect(isDirty('a', 'b')).toBe(true)
    expect(isDirty('', null)).toBe(false)
  })
})
