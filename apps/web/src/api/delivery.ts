import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// Hardening and delivery of a project (M9a, ADR-0023): the hardening report of the newest generation and the
// releases (`code.view`), and a push of the generated code to a new branch of the customer's repository
// (`code.push`). The repository token never reaches the browser.
export type Hardening = Schemas['HardeningOut']
export type HardeningFinding = Schemas['HardeningFindingOut']
export type Release = Schemas['ReleaseOut']

/** The project permission the push requires. */
export const CODE_PUSH = 'code.push'
export const SEVERITIES = ['critical', 'high', 'medium', 'low'] as const

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

const keys = {
  hardening: (projectId: string) => ['projects', projectId, 'hardening'],
  releases: (projectId: string) => ['projects', projectId, 'releases'],
} as const

/** `null` until a run hardens the generated code. */
export const useHardening = (projectId: string, enabled = true) =>
  useQuery({
    queryKey: keys.hardening(projectId),
    queryFn: () =>
      unwrap(api.GET('/api/v1/projects/{project_id}/hardening', { params: { path: { project_id: projectId } } })),
    enabled,
  })

export const useReleases = (projectId: string, enabled = true) =>
  useQuery({
    queryKey: keys.releases(projectId),
    queryFn: () =>
      unwrap(api.GET('/api/v1/projects/{project_id}/releases', { params: { path: { project_id: projectId } } })),
    enabled,
  })

export function usePushCode(projectId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () =>
      unwrap(api.POST('/api/v1/projects/{project_id}/code:push', { params: { path: { project_id: projectId } } })),
    onSettled: () => client.invalidateQueries({ queryKey: keys.releases(projectId) }),
  })
}

/** The findings of a report counted by severity, in the order of the badges. */
export function severityCounts(report: Pick<Hardening, 'counts'>): { severity: string; count: number }[] {
  return SEVERITIES.map((severity) => ({ severity, count: report.counts[severity] ?? 0 })).filter((s) => s.count > 0)
}
