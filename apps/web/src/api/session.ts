import { queryOptions, useQuery, type QueryClient } from '@tanstack/react-query'
import { api, setCsrfToken, toApiError, type Schemas } from './client'
import { registerLanguagePersister, setLanguage } from '@/i18n'

// The signed-in session, from the BFF (spec 15.1). Authentication is done by Keycloak (or dev-auth in
// development); this module only asks the API who is signed in.
export type Me = Schemas['MeOut']
export type DevUser = Schemas['DevUser']

async function fetchMe(): Promise<Me | null> {
  const { data, error, response } = await api.GET('/api/v1/me')
  if (response.status === 401) {
    setCsrfToken(null)
    return null
  }
  if (!data) throw toApiError(response, error)
  setCsrfToken(data.csrfToken)
  // The server-side preference wins over the browser's (it follows the user across devices, spec 18.6).
  setLanguage(data.user.locale, { persist: false })
  return data
}

export const meQuery = queryOptions({ queryKey: ['me'], queryFn: fetchMe })

export function useMe() {
  return useQuery(meQuery).data ?? null
}

registerLanguagePersister(async (locale) => {
  await api.PATCH('/api/v1/me', { body: { locale } })
})

/** Redirect to Keycloak through the BFF; it comes back to `returnTo` with the session cookie set. */
export function startSignIn(returnTo = '/') {
  window.location.assign(`/auth/login?returnTo=${encodeURIComponent(returnTo)}`)
}

export async function signOut(client: QueryClient) {
  await api.POST('/auth/logout')
  setCsrfToken(null)
  client.clear()
}

export async function switchTenant(client: QueryClient, tenantId: string) {
  const { error, response } = await api.PUT('/api/v1/session/tenant', { body: { tenantId } })
  if (!response.ok) throw toApiError(response, error)
  // Everything shown so far belongs to the previous tenant.
  await client.invalidateQueries()
}

/** Seeded users for dev-auth; null when dev-auth is not enabled (the route does not exist). */
export async function fetchDevUsers(): Promise<DevUser[] | null> {
  const { data, response } = await api.GET('/auth/dev/users')
  return response.ok && data ? data : null
}

export async function devSignIn(client: QueryClient, userId: string) {
  const { error, response } = await api.POST('/auth/dev/login', { body: { userId } })
  if (!response.ok) throw toApiError(response, error)
  await client.invalidateQueries({ queryKey: ['me'] })
}

export { can, canOpen, initials, isPlatformOperator, type NavKey } from './access'
