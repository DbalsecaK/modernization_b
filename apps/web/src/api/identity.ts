import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// Administration → Authentication (M0b, ADR-0022): how the active tenant signs in. The client secret of a provider
// is sent once to the API, which hands it to Keycloak; it never comes back.
export type Identity = Schemas['IdentityOut']
export type IdentityProvider = Schemas['ProviderOut']
export type ProviderCreate = Schemas['ProviderCreate']
export type ProviderUpdate = Schemas['ProviderUpdate']
/** The tenant permission that configures sign-in (the API checks it anyway). */
export const IDENTITY_MANAGE = 'identity.manage'

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

const identityKey = ['admin', 'identity'] as const
const auditKey = ['admin', 'audit'] as const

function useIdentityMutation<A, R>(fn: (args: A) => Promise<R>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await Promise.all([identityKey, auditKey].map((queryKey) => client.invalidateQueries({ queryKey })))
    },
  })
}

export const useIdentity = (enabled = true) =>
  useQuery({ queryKey: identityKey, queryFn: () => unwrap(api.GET('/api/v1/identity')), enabled })
export const useSaveIdentity = () =>
  useIdentityMutation((body: Schemas['IdentityUpdate']) => unwrap(api.PUT('/api/v1/identity', { body })))
export const useCreateProvider = () =>
  useIdentityMutation((body: ProviderCreate) => unwrap(api.POST('/api/v1/identity/providers', { body })))
export const useUpdateProvider = () =>
  useIdentityMutation(({ id, ...body }: ProviderUpdate & { id: string }) =>
    unwrap(api.PATCH('/api/v1/identity/providers/{provider_id}', { params: { path: { provider_id: id } }, body })),
  )
export const useApplyProvider = () =>
  useIdentityMutation((id: string) =>
    unwrap(api.POST('/api/v1/identity/providers/{provider_id}:apply', { params: { path: { provider_id: id } } })),
  )
export const useDeleteProvider = () =>
  useIdentityMutation((id: string) =>
    unwrap(api.DELETE('/api/v1/identity/providers/{provider_id}', { params: { path: { provider_id: id } } })),
  )

/** Starting points for the usual providers: what the issuer looks like and what to ask for. */
export const PRESETS = {
  entra: { issuer: 'https://login.microsoftonline.com/<tenant-id>/v2.0', scopes: 'openid email profile' },
  okta: { issuer: 'https://<your-org>.okta.com/oauth2/default', scopes: 'openid email profile groups' },
  google: { issuer: 'https://accounts.google.com', scopes: 'openid email profile' },
  other: { issuer: 'https://', scopes: 'openid email profile' },
} as const
export type Preset = keyof typeof PRESETS

/** "a.example, b.example" → ["a.example", "b.example"] (lowercase, no blanks, no repeats). */
export function parseDomains(value: string): string[] {
  return [
    ...new Set(
      value
        .split(/[\s,;]+/)
        .map((d) => d.trim().toLowerCase().replace(/\.$/, ''))
        .filter(Boolean),
    ),
  ]
}

/** The group → role rows of the form as the API's mapping (rows without a group or a role are dropped). */
export function toGroupRoles(rows: { group: string; role: string }[]): Record<string, string> {
  return Object.fromEntries(rows.filter((r) => r.group.trim() && r.role).map((r) => [r.group.trim(), r.role]))
}
