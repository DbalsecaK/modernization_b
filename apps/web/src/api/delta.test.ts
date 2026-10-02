import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DeltaOut } from './delta'

// The delta call against a stubbed fetch: the client is built when its module loads, so the globals are stubbed first
// and the module is imported afterwards.
const delta = (extra: Partial<DeltaOut> = {}): DeltaOut => ({
  inventory: { stack: 'spring-boot', endpoints: [], tables: [] },
  baseline: { passed: ['LoanServiceTest.creates'], failed: [] },
  design: { changes: [], decisions: [] },
  added: ['src/main/java/demo/RateController.java'],
  changed: ['src/main/java/demo/LoanService.java'],
  report: '# DELTA\n',
  ...extra,
})

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': status >= 400 ? 'application/problem+json' : 'application/json' },
  })

let calls: Request[] = []

async function load(reply: (request: Request) => Response) {
  calls = []
  vi.stubGlobal('location', { origin: 'http://localhost' })
  vi.stubGlobal('fetch', async (request: Request) => {
    calls.push(request)
    return reply(request)
  })
  vi.resetModules()
  return import('./delta')
}

describe('delta API', () => {
  beforeEach(() => vi.resetModules())
  afterEach(() => vi.unstubAllGlobals())

  it('reads the delta of the project', async () => {
    const { fetchDelta } = await load(() => json(200, delta()))
    const got = await fetchDelta('p1')
    expect(calls[0].method).toBe('GET')
    expect(new URL(calls[0].url).pathname).toBe('/api/v1/projects/p1/delta')
    expect(got.added).toEqual(['src/main/java/demo/RateController.java'])
    expect(got.baseline).toEqual({ passed: ['LoanServiceTest.creates'], failed: [] })
    expect(got.report).toBe('# DELTA\n')
  })

  it('before the intake every part is empty', async () => {
    const empty = delta({ inventory: null, baseline: null, design: null, added: [], changed: [], report: null })
    const { fetchDelta } = await load(() => json(200, empty))
    expect(await fetchDelta('p1')).toEqual(empty)
  })

  it('without permission it is a 403 with the API problem detail', async () => {
    const detail = 'You do not have the code.view permission on this project.'
    const { fetchDelta } = await load(() => json(403, { status: 403, code: 'forbidden', detail }))
    const { ApiError } = await import('./client')
    const error = await fetchDelta('p1').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 403, code: 'forbidden', message: detail })
  })
})
