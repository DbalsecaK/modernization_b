import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// Runs of the pipeline, their gates and questions, My tasks and the live activity (spec 10.4, 18.2, 18.8).
// The API records decisions and enqueues the worker; the screens refresh from the event stream.
export type Run = Schemas['RunOut']
export type RunDetail = Schemas['RunDetail']
export type PhaseRun = Schemas['PhaseRunOut']
export type Invocation = Schemas['InvocationOut']
export type GateRow = Schemas['GateOut']
export type Question = Schemas['QuestionOut']
export type Task = Schemas['TaskOut']
export type ActivityEvent = Schemas['ActivityEventOut']
export type RunKind = Schemas['RunIn']['kind']
export type Gate = 'C1' | 'C2' | 'C3' | 'C4'

export const ACTIVE_STATUSES: Run['status'][] = ['queued', 'running', 'waiting']

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

const keys = {
  runs: (projectId: string) => ['projects', projectId, 'runs'],
  run: (projectId: string, runId: string) => ['projects', projectId, 'runs', runId],
  questions: (projectId: string) => ['projects', projectId, 'questions'],
  tasks: ['tasks'],
} as const

function useInvalidate() {
  const client = useQueryClient()
  return (projectId: string) =>
    Promise.all([
      client.invalidateQueries({ queryKey: ['projects', projectId] }),
      client.invalidateQueries({ queryKey: keys.tasks }),
    ])
}

export const useRuns = (projectId: string) =>
  useQuery({
    queryKey: keys.runs(projectId),
    queryFn: () =>
      unwrap(api.GET('/api/v1/projects/{project_id}/runs', { params: { path: { project_id: projectId } } })),
  })

export const useRun = (projectId: string, runId: string | null) =>
  useQuery({
    queryKey: keys.run(projectId, runId ?? ''),
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/projects/{project_id}/runs/{run_id}', {
          params: { path: { project_id: projectId, run_id: runId! } },
        }),
      ),
    enabled: !!runId,
    // The event stream refreshes it; polling while the run is live is the backstop for a missed event.
    refetchInterval: (query) => (query.state.data && ACTIVE_STATUSES.includes(query.state.data.status) ? 5_000 : false),
  })

export function useStartRun(projectId: string) {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (body: Schemas['RunIn']) =>
      unwrap(api.POST('/api/v1/projects/{project_id}/runs', { params: { path: { project_id: projectId } }, body })),
    onSuccess: () => invalidate(projectId),
  })
}

export function useCancelRun(projectId: string) {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (runId: string) =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/runs/{run_id}:cancel', {
          params: { path: { project_id: projectId, run_id: runId } },
        }),
      ),
    onSuccess: () => invalidate(projectId),
  })
}

export function useDecideGate(projectId: string) {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({
      runId,
      gate,
      approve,
      comment,
    }: {
      runId: string
      gate: Gate
      approve: boolean
      comment?: string
    }) => {
      const params = { path: { project_id: projectId, run_id: runId, gate } }
      const body = { comment: comment || null }
      return unwrap(
        approve
          ? api.POST('/api/v1/projects/{project_id}/runs/{run_id}/gates/{gate}:approve', { params, body })
          : api.POST('/api/v1/projects/{project_id}/runs/{run_id}/gates/{gate}:reject', { params, body }),
      )
    },
    onSuccess: () => invalidate(projectId),
  })
}

export const useQuestions = (projectId: string) =>
  useQuery({
    queryKey: keys.questions(projectId),
    queryFn: () =>
      unwrap(api.GET('/api/v1/projects/{project_id}/questions', { params: { path: { project_id: projectId } } })),
  })

export function useAnswerQuestion() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({
      projectId,
      questionId,
      body,
    }: {
      projectId: string
      questionId: string
      body: Schemas['AnswerIn']
    }) =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/questions/{question_id}:answer', {
          params: { path: { project_id: projectId, question_id: questionId } },
          body,
        }),
      ),
    onSuccess: (_data, { projectId }) => invalidate(projectId),
  })
}

export function useAcceptRecommended() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ projectId, questionIds }: { projectId: string; questionIds?: string[] }) =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/questions:accept-recommended', {
          params: { path: { project_id: projectId } },
          body: { questionIds: questionIds ?? null },
        }),
      ),
    onSuccess: (_data, { projectId }) => invalidate(projectId),
  })
}

export const useTasks = (enabled = true) =>
  useQuery({
    queryKey: keys.tasks,
    queryFn: () => unwrap(api.GET('/api/v1/tasks')),
    refetchInterval: 30_000,
    enabled,
  })

const MAX_EVENTS = 200

/**
 * Live events over SSE (EventSource reconnects by itself and sends Last-Event-ID, so nothing is missed). With a
 * project and run it follows that run; otherwise every project the user may see. Newest first.
 */
export function useActivityStream(scope?: { projectId: string; runId: string }, enabled = true) {
  // Events belong to the stream they came from: switching runs starts from an empty list.
  const [received, setReceived] = useState<{ url: string; events: ActivityEvent[] }>({ url: '', events: [] })
  const [connected, setConnected] = useState(false)
  const client = useQueryClient()
  const seen = useRef(new Set<number>())
  const url = scope ? `/api/v1/projects/${scope.projectId}/runs/${scope.runId}/events` : '/api/v1/activity/events'

  useEffect(() => {
    if (!enabled || typeof EventSource === 'undefined') return
    seen.current = new Set()
    const source = new EventSource(url, { withCredentials: true })
    source.onopen = () => setConnected(true)
    source.onerror = () => setConnected(false)
    source.addEventListener('activity', (message) => {
      const event = JSON.parse((message as MessageEvent<string>).data) as ActivityEvent
      if (seen.current.has(event.id)) return
      seen.current.add(event.id)
      setReceived((current) => ({
        url,
        events: [event, ...(current.url === url ? current.events : [])].slice(0, MAX_EVENTS),
      }))
      // Runs, gates, questions and tasks change with these events: refresh what the screens show.
      if (
        ['phaseCompleted', 'gateWaiting', 'questionAsked', 'runFinished', 'phaseStarted', 'escalated'].includes(
          event.kind,
        )
      ) {
        void client.invalidateQueries({ queryKey: ['projects', event.projectId] })
        void client.invalidateQueries({ queryKey: keys.tasks })
      }
    })
    return () => source.close()
  }, [url, enabled, client])

  return { events: received.url === url ? received.events : [], connected }
}

/**
 * Events are append-only: a "started" event stays running forever. It is still running only while no newer event of
 * the same invocation (or, without one, of the same run and phase) has arrived. `events` is newest first.
 */
export function effectiveStatuses(events: ActivityEvent[]): Map<number, ActivityEvent['status']> {
  const seen = new Set<string>()
  const statuses = new Map<number, ActivityEvent['status']>()
  for (const e of events) {
    const key = e.invocationId ?? `${e.runId}:${e.phase ?? ''}`
    statuses.set(e.id, e.status === 'running' && seen.has(key) ? 'succeeded' : e.status)
    seen.add(key)
  }
  return statuses
}

/** The JSON of one event, without secrets (redacted by the server), as a file. */
export async function downloadEvent(eventId: number) {
  const response = await fetch(`/api/v1/activity/events/${eventId}/export`, { credentials: 'same-origin' })
  if (!response.ok) throw toApiError(response, await response.json().catch(() => null))
  const blob = await response.blob()
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = `activity-event-${eventId}.json`
  link.click()
  URL.revokeObjectURL(href)
}
