import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// The project's backlog in Jira or Azure DevOps (spec 7.6, ADR-0019): the link, the synced items and the corrections
// the developer agent proposed for bugs. The sync runs in the worker; the screen asks for it and shows the result.
export type Backlog = Schemas['BacklogOut']
export type BacklogInput = Schemas['BacklogIn']
export type WorkItem = Schemas['WorkItemOut']
export type BugFix = Schemas['BugFixOut']

/** The project permission that links and syncs the backlog (the API checks it anyway). */
export const PROJECT_CONFIGURE = 'project.configure'

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

const key = (projectId: string) => ['backlog', projectId] as const

export const useBacklog = (projectId: string) =>
  useQuery({
    queryKey: key(projectId),
    queryFn: () =>
      unwrap(api.GET('/api/v1/projects/{project_id}/backlog', { params: { path: { project_id: projectId } } })),
    // While a sync is running in the worker, the items arrive a moment later.
    refetchInterval: 10_000,
  })

function useBacklogMutation<A, R>(projectId: string, fn: (args: A) => Promise<R>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: key(projectId) })
    },
  })
}

export const useLinkBacklog = (projectId: string) =>
  useBacklogMutation(projectId, (body: BacklogInput) =>
    unwrap(api.PUT('/api/v1/projects/{project_id}/backlog', { params: { path: { project_id: projectId } }, body })),
  )

export const useUnlinkBacklog = (projectId: string) =>
  useBacklogMutation(projectId, () =>
    unwrap(api.DELETE('/api/v1/projects/{project_id}/backlog', { params: { path: { project_id: projectId } } })),
  )

export const useSyncBacklog = (projectId: string) =>
  useBacklogMutation(projectId, () =>
    unwrap(api.POST('/api/v1/projects/{project_id}/backlog:sync', { params: { path: { project_id: projectId } } })),
  )
