import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// The adapter studio (ADR-0039): the tenant's declared source adapters, tried on samples and drafted by a model.
export type TenantAdapter = Schemas['TenantAdapterOut']
export type AdapterSpec = Record<string, unknown>
export type TryResult = Schemas['TryOut']
export type DraftResult = Schemas['DraftOut']
export type Sample = { path: string; text: string }

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

const key = ['admin', 'adapters'] as const

export const useTenantAdapters = (enabled = true) =>
  useQuery({ queryKey: key, queryFn: () => unwrap(api.GET('/api/v1/adapters')), enabled })

function useRefreshing<A, R>(fn: (args: A) => Promise<R>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await Promise.all(
        [key, ['catalog'], ['admin', 'audit']].map((queryKey) => client.invalidateQueries({ queryKey })),
      )
    },
  })
}

export const useCreateAdapter = () =>
  useRefreshing((spec: AdapterSpec) => unwrap(api.POST('/api/v1/adapters', { body: { spec } })))

export const useDeleteAdapter = () =>
  useRefreshing((id: string) =>
    unwrap(api.DELETE('/api/v1/adapters/{adapter_id}', { params: { path: { adapter_id: id } } })),
  )

export function tryAdapter(spec: AdapterSpec, samples: Sample[]): Promise<TryResult> {
  return unwrap(api.POST('/api/v1/adapters:try', { body: { spec, samples } }))
}

export function draftAdapter(description: string, samples: Sample[], key?: string): Promise<DraftResult> {
  return unwrap(api.POST('/api/v1/adapters:draft', { body: { description, samples, key: key || null } }))
}
