import { describe, expect, it } from 'vitest'
import { effectiveStatuses, type ActivityEvent } from './runs'

function event(id: number, status: ActivityEvent['status'], extra: Partial<ActivityEvent> = {}): ActivityEvent {
  return {
    id,
    projectId: 'p',
    runId: 'r',
    invocationId: null,
    agentKey: null,
    phase: 'inventory',
    kind: 'info',
    status,
    message: '',
    model: null,
    tokens: 0,
    costUsd: null,
    payload: {},
    occurredAt: '2026-09-29T10:00:00Z',
    ...extra,
  }
}

describe('effectiveStatuses', () => {
  it('a started event stops counting as running once its invocation reports again', () => {
    const newestFirst = [
      event(3, 'succeeded', { invocationId: 'a' }),
      event(2, 'running', { invocationId: 'b' }),
      event(1, 'running', { invocationId: 'a' }),
    ]
    const statuses = effectiveStatuses(newestFirst)
    expect(statuses.get(1)).toBe('succeeded')
    expect(statuses.get(2)).toBe('running')
  })

  it('without an invocation, the phase of the run is the key', () => {
    const statuses = effectiveStatuses([
      event(2, 'succeeded'),
      event(1, 'running'),
      event(0, 'running', { phase: 'domains' }),
    ])
    expect(statuses.get(1)).toBe('succeeded')
    expect(statuses.get(0)).toBe('running')
  })

  it('failures and waits are kept as they are', () => {
    const statuses = effectiveStatuses([event(2, 'succeeded'), event(1, 'failed')])
    expect(statuses.get(1)).toBe('failed')
  })
})
