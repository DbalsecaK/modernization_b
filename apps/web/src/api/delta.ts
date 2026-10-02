import { useQuery } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// The delta of Flow 3 (ADR-0026) added to an existing Spring Boot application: the AS-IS inventory, the baseline of
// its tests before the delta, the delta design approved at C3, the files the delta adds and changes, and DELTA.md.
// Reading needs `code.view`.
export type DeltaOut = Schemas['DeltaOut']

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

const keys = {
  delta: (projectId: string) => ['projects', projectId, 'delta'],
} as const

export const fetchDelta = (projectId: string) =>
  unwrap(api.GET('/api/v1/projects/{project_id}/delta', { params: { path: { project_id: projectId } } }))

export const useDelta = (projectId: string, enabled = true) =>
  useQuery({ queryKey: keys.delta(projectId), queryFn: () => fetchDelta(projectId), enabled })
