import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// The independent validation of a third party's target (Flow 4, ADR-0025): what the worker read of the target, the
// interface mapping a person corrects before gate C2, the problems the server finds in it by code, the rule
// comparison and the report. Reading needs `code.view`; saving the mapping needs `gate.c2.approve`.
export type IvvOut = Schemas['IvvOut']

/** The project permission that allows changing the mapping (it is part of approving C2). */
export const IVV_EDIT_MAPPING = 'gate.c2.approve'

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

const keys = {
  ivv: (projectId: string) => ['projects', projectId, 'ivv'],
} as const

const path = (projectId: string) => ({ params: { path: { project_id: projectId } } })

export const fetchIvv = (projectId: string) => unwrap(api.GET('/api/v1/projects/{project_id}/ivv', path(projectId)))

/**
 * Saves a person's mapping. Problems do not block saving: they come back in the result. Unreadable YAML or a wrong
 * shape is 422 `invalid_mapping`; before the target intake there is nothing to correct (404 `ivv_mapping_not_found`).
 */
export const saveIvvMapping = (projectId: string, mapping: string) =>
  unwrap(api.PUT('/api/v1/projects/{project_id}/ivv/mapping', { ...path(projectId), body: { mapping } }))

export const useIvv = (projectId: string, enabled = true) =>
  useQuery({ queryKey: keys.ivv(projectId), queryFn: () => fetchIvv(projectId), enabled })

/**
 * The handlers run at the mutation level: they fire even when the saved version remounts the editor (callbacks given
 * to `mutate` would be dropped then).
 */
export function useSaveIvvMapping(
  projectId: string,
  handlers: { onSuccess?: (saved: IvvOut) => void; onError?: (error: Error) => void } = {},
) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (mapping: string) => saveIvvMapping(projectId, mapping),
    onSuccess: (saved) => {
      client.setQueryData(keys.ivv(projectId), saved)
      handlers.onSuccess?.(saved)
    },
    onError: (error) => handlers.onError?.(error),
  })
}
