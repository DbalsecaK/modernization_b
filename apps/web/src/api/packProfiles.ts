import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// Pack profiles of the tenant (ADR-0040): a package root the design must respect and conventions the agents are
// told; the pack itself stays the platform's.
export type PackProfile = Schemas['PackProfileOut']
export type PackProfileInput = Schemas['PackProfileIn']

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

const key = ['admin', 'pack-profiles'] as const

export const usePackProfiles = (enabled = true) =>
  useQuery({ queryKey: key, queryFn: () => unwrap(api.GET('/api/v1/pack-profiles')), enabled })

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

export const useCreatePackProfile = () =>
  useRefreshing((body: PackProfileInput) => unwrap(api.POST('/api/v1/pack-profiles', { body })))

export const useDeletePackProfile = () =>
  useRefreshing((id: string) =>
    unwrap(api.DELETE('/api/v1/pack-profiles/{profile_id}', { params: { path: { profile_id: id } } })),
  )
