import { describe, expect, it } from 'vitest'
import type { Design } from '@/api/architecture'
import { contextSummary, contractText } from './model'

const makeUseCase = (name: string, rules: string[]) => ({
  name,
  description: '',
  rules,
  httpMethod: 'POST',
  path: '',
  ports: [],
  legacyProgram: null,
  errors: [],
})

const design: Design = {
  runId: 'run-1',
  createdAt: '2026-09-30T10:00:00Z',
  context: 'payments',
  basePackage: 'com.example.payments',
  entities: [],
  ports: [],
  useCases: [makeUseCase('PayOrder', ['RULE-001', 'RULE-002']), makeUseCase('CancelOrder', ['RULE-002', 'RULE-003'])],
  decisions: [],
  infrastructure: [],
}

describe('contextSummary', () => {
  it('counts distinct rules and one service and endpoint per use case', () => {
    expect(contextSummary(design)).toEqual({
      name: 'payments',
      rules: 3,
      services: ['PayOrderService', 'CancelOrderService'],
      endpoints: 2,
    })
  })
})

describe('contractText', () => {
  it('pretty-prints and cuts long documents', () => {
    expect(contractText({ a: 1 })).toEqual({ text: '{\n  "a": 1\n}', truncated: false })
    const long = contractText({ paths: Object.fromEntries(Array.from({ length: 50 }, (_, i) => [`/p${i}`, {}])) }, 10)
    expect(long.text.split('\n')).toHaveLength(10)
    expect(long.truncated).toBe(true)
  })
})
