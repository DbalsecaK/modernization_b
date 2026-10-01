import { useQuery } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// The architecture of the target (spec 18.3): the design approved at C3 and the HTTP contract derived from it, both
// documents the worker stored. Seeing the project is enough (they describe the target, not its code).
export type Design = Schemas['DesignOut']
export type DesignUseCase = Schemas['DesignUseCaseOut']
export type Contracts = Schemas['ContractsOut']
export type Operation = Schemas['OperationOut']

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

const path = (projectId: string) => ({ params: { path: { project_id: projectId } } })

/** `null` before the design phase. */
export const useDesign = (projectId: string) =>
  useQuery({
    queryKey: ['projects', projectId, 'design'],
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/design', path(projectId))),
  })

/** `null` before the design phase. */
export const useContracts = (projectId: string) =>
  useQuery({
    queryKey: ['projects', projectId, 'contracts'],
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/contracts', path(projectId))),
  })
