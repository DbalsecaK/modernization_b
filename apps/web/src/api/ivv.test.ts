import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { IvvOut } from './ivv'

// The IV&V calls against a stubbed fetch: the client is built when its module loads, so the globals are stubbed first
// and the module is imported afterwards.
const MAPPING = 'programs:\n  - legacy: sp_loans\n    endpoint: { method: POST, path: /loans }\n'

const ivv = (extra: Partial<IvvOut> = {}): IvvOut => ({
  inventory: { stack: 'spring-boot', endpoints: [], tables: [] },
  mapping: MAPPING,
  mappingUpdatedAt: '2026-10-01T10:00:00Z',
  gaps: [],
  problems: [],
  comparison: null,
  report: null,
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
  return import('./ivv')
}

describe('IV&V API', () => {
  beforeEach(() => vi.resetModules())
  afterEach(() => vi.unstubAllGlobals())

  it('reads the inventory and the mapping of the project', async () => {
    const { fetchIvv } = await load(() => json(200, ivv()))
    const got = await fetchIvv('p1')
    expect(calls[0].method).toBe('GET')
    expect(new URL(calls[0].url).pathname).toBe('/api/v1/projects/p1/ivv')
    expect(got.mapping).toBe(MAPPING)
    expect(got.inventory).toMatchObject({ stack: 'spring-boot' })
  })

  it('saving returns the problems the server found (they do not block saving)', async () => {
    const problems = ['sp_loans: the request field amount is not a legacy parameter']
    const { saveIvvMapping } = await load(() => json(200, ivv({ problems })))
    const saved = await saveIvvMapping('p1', MAPPING)
    expect(calls[0].method).toBe('PUT')
    expect(new URL(calls[0].url).pathname).toBe('/api/v1/projects/p1/ivv/mapping')
    expect(await calls[0].json()).toEqual({ mapping: MAPPING })
    expect(saved.problems).toEqual(problems)
  })

  it('an unreadable mapping is a 422 with the API problem detail', async () => {
    const detail = 'The mapping cannot be read: mapping values are not allowed here'
    const { saveIvvMapping } = await load(() =>
      json(422, { type: 'about:blank', status: 422, code: 'invalid_mapping', detail }),
    )
    const { ApiError } = await import('./client')
    const error = await saveIvvMapping('p1', 'programs: [').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 422, code: 'invalid_mapping', message: detail })
  })

  it('before the target intake there is no mapping to save (404)', async () => {
    const { saveIvvMapping } = await load(() =>
      json(404, { status: 404, code: 'ivv_mapping_not_found', detail: 'The ivv mapping does not exist.' }),
    )
    await expect(saveIvvMapping('p1', MAPPING)).rejects.toMatchObject({ status: 404, code: 'ivv_mapping_not_found' })
  })
})
