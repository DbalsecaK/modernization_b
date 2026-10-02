import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// AI configuration and usage of the active tenant (spec 12, 13). The API key of a connection goes to the
// secrets store on the server and never comes back; every model call goes through the server's gateway.
// Local models (ADR-0030): written by hand until the schema is regenerated; the intersections stay valid after.
export type ConnectionProvider = 'openrouter' | 'openai-compatible'
export type Connection = Omit<Schemas['ConnectionOut'], 'provider'> & {
  provider: ConnectionProvider
  baseUrl?: string | null
}
export type ConnectionCreateInput = {
  provider: ConnectionProvider
  name: string
  apiKey?: string | null
  baseUrl?: string | null
}
export type ConnectionUpdateInput = { name?: string; apiKey?: string; baseUrl?: string }
export type Offering = Schemas['OfferingOut'] & { provider?: ConnectionProvider; connectionId?: string | null }
export type CatalogVersion = Omit<Schemas['VersionOut'], 'offerings'> & { offerings: Offering[] }
export type ServedModel = { slug: string; contextWindow: number | null }
export type Capability = 'tools' | 'structured_output' | 'reasoning' | 'vision'
export type LocalModelInput = {
  slug: string
  name?: string | null
  contextWindow?: number | null
  maxOutputTokens?: number | null
  capabilities?: Capability[]
  zdr?: boolean
  inputPerMtok?: string
  outputPerMtok?: string
}
export type LocalModelAdded = { offeringId: string; slug: string }
export type Price = Schemas['PriceOut']
export type Profile = Schemas['ProfileOut']
export type ProfileInput = Schemas['ProfileIn']
export type ProfileTest = Schemas['ProfileTestOut']
export type Assignment = Schemas['ModelAssignmentOut']
export type AssignmentInput = Schemas['ModelAssignmentIn']
export type Policy = Schemas['PolicyOut']
export type PolicyInput = Schemas['PolicyIn']
export type UsageSummary = Schemas['UsageSummary']
export type UsageRow = Schemas['UsageRow']
export type Budget = Schemas['BudgetOut']
export type BudgetInput = Schemas['BudgetIn']
export type Effort = Profile['effort']
export type GroupBy = UsageSummary['groupBy']

export const EFFORTS: Effort[] = ['low', 'medium', 'high', 'max']

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

/** The routes the generated schema does not list yet (local models); the CSRF middleware still applies. */
type LooseInit = { params?: { path?: Record<string, string> }; body?: unknown }
const loose = api as unknown as {
  GET: (path: string, init?: LooseInit) => Promise<Result<unknown>>
  POST: (path: string, init?: LooseInit) => Promise<Result<unknown>>
  PATCH: (path: string, init?: LooseInit) => Promise<Result<unknown>>
}

/** Money and prices travel as decimal strings; the screens show them as numbers. */
export const usd = (value: string | number | null | undefined) => (value == null ? null : Number(value))

const keys = {
  connections: ['ai', 'connections'],
  catalog: ['ai', 'catalog'],
  profiles: ['ai', 'profiles'],
  assignments: ['ai', 'assignments'],
  options: ['ai', 'assignment-options'],
  policy: ['ai', 'policy'],
  offering: ['ai', 'offering'],
  usage: ['usage'],
  budgets: ['budgets'],
} as const

function useAiMutation<A, R>(fn: (args: A) => Promise<R>, refresh: readonly (readonly string[])[]) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await Promise.all(refresh.map((queryKey) => client.invalidateQueries({ queryKey })))
    },
  })
}

// Connections
export const useConnections = () =>
  useQuery({
    queryKey: keys.connections,
    queryFn: () => unwrap(api.GET('/api/v1/ai/connections')) as Promise<Connection[]>,
  })

export const useCreateConnection = () =>
  useAiMutation(
    (body: ConnectionCreateInput) => unwrap(loose.POST('/api/v1/ai/connections', { body })) as Promise<Connection>,
    [keys.connections],
  )

export const useUpdateConnection = () =>
  useAiMutation(
    ({ id, ...body }: ConnectionUpdateInput & { id: string }) =>
      unwrap(
        loose.PATCH('/api/v1/ai/connections/{connection_id}', { params: { path: { connection_id: id } }, body }),
      ) as Promise<Connection>,
    [keys.connections],
  )

/** What an openai-compatible server lists at `<base>/models` (fetched on demand). */
export const useServedModels = (connectionId: string | null, enabled: boolean) =>
  useQuery({
    queryKey: [...keys.connections, connectionId, 'served-models'],
    queryFn: () =>
      unwrap(
        loose.GET('/api/v1/ai/connections/{connection_id}/served-models', {
          params: { path: { connection_id: connectionId! } },
        }),
      ) as Promise<ServedModel[]>,
    enabled: enabled && !!connectionId,
    retry: false,
  })

/** Add a model of an openai-compatible connection, with the price the tenant declares (zero by default). */
export const useAddLocalModel = () =>
  useAiMutation(
    ({ connectionId, ...body }: LocalModelInput & { connectionId: string }) =>
      unwrap(
        loose.POST('/api/v1/ai/connections/{connection_id}/models', {
          params: { path: { connection_id: connectionId } },
          body,
        }),
      ) as Promise<LocalModelAdded>,
    [keys.catalog],
  )

export const useDeleteConnection = () =>
  useAiMutation(
    (id: string) =>
      unwrap(api.DELETE('/api/v1/ai/connections/{connection_id}', { params: { path: { connection_id: id } } })),
    [keys.connections],
  )

export const useTestConnection = () =>
  useAiMutation(
    (id: string) =>
      unwrap(api.POST('/api/v1/ai/connections/{connection_id}:test', { params: { path: { connection_id: id } } })),
    [keys.connections],
  )

// Catalog
export const useCatalog = (search: string, onlyOffered: boolean) =>
  useQuery({
    queryKey: [...keys.catalog, search, onlyOffered],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/ai/catalog', {
          params: { query: { search: search || undefined, only_offered: onlyOffered } },
        }),
      ) as Promise<CatalogVersion[]>,
    placeholderData: keepPreviousData,
  })

export const useSyncCatalog = () => useAiMutation(() => unwrap(api.POST('/api/v1/ai/catalog:sync')), [keys.catalog])

export const useLoadOfferings = () =>
  useAiMutation(
    (versionId: string) =>
      unwrap(
        api.POST('/api/v1/ai/catalog/versions/{version_id}:load-offerings', {
          params: { path: { version_id: versionId } },
        }),
      ),
    [keys.catalog],
  )

export const useEffortMapping = (offeringId: string | null) =>
  useQuery({
    queryKey: [...keys.offering, offeringId, 'effort'],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/ai/offerings/{offering_id}/effort-mapping', {
          params: { path: { offering_id: offeringId! } },
        }),
      ),
    enabled: !!offeringId,
  })

export const useSetEffortMapping = () =>
  useAiMutation(
    ({ offeringId, parameters }: { offeringId: string; parameters: Schemas['EffortMappingIn']['parameters'] }) =>
      unwrap(
        api.PUT('/api/v1/ai/offerings/{offering_id}/effort-mapping', {
          params: { path: { offering_id: offeringId } },
          body: { parameters },
        }),
      ),
    [keys.offering],
  )

export const usePrices = (offeringId: string | null) =>
  useQuery({
    queryKey: [...keys.offering, offeringId, 'prices'],
    queryFn: () =>
      unwrap(api.GET('/api/v1/ai/offerings/{offering_id}/prices', { params: { path: { offering_id: offeringId! } } })),
    enabled: !!offeringId,
  })

export const useAddPrice = () =>
  useAiMutation(
    ({ offeringId, ...body }: Schemas['ManualPriceIn'] & { offeringId: string }) =>
      unwrap(
        api.POST('/api/v1/ai/offerings/{offering_id}/prices', { params: { path: { offering_id: offeringId } }, body }),
      ),
    [keys.offering, keys.catalog],
  )

// Profiles
export const useProfiles = (enabled = true) =>
  useQuery({ queryKey: keys.profiles, queryFn: () => unwrap(api.GET('/api/v1/ai/profiles')), enabled })

export const useSaveProfile = () =>
  useAiMutation(
    ({ id, body }: { id: string | null; body: ProfileInput }) =>
      id
        ? unwrap(api.PUT('/api/v1/ai/profiles/{profile_id}', { params: { path: { profile_id: id } }, body }))
        : unwrap(api.POST('/api/v1/ai/profiles', { body })),
    [keys.profiles],
  )

export const useDeleteProfile = () =>
  useAiMutation(
    (id: string) => unwrap(api.DELETE('/api/v1/ai/profiles/{profile_id}', { params: { path: { profile_id: id } } })),
    [keys.profiles, keys.assignments],
  )

export const useTestProfile = () =>
  useAiMutation(
    (id: string) => unwrap(api.POST('/api/v1/ai/profiles/{profile_id}:test', { params: { path: { profile_id: id } } })),
    [keys.usage, keys.budgets],
  )

// Assignment matrix and policy
export const useAssignmentOptions = () =>
  useQuery({
    queryKey: keys.options,
    queryFn: () => unwrap(api.GET('/api/v1/ai/assignment-options')),
    staleTime: Infinity,
  })

export const useAssignments = (projectId: string | null) =>
  useQuery({
    queryKey: [...keys.assignments, projectId],
    queryFn: () =>
      unwrap(api.GET('/api/v1/ai/assignments', { params: { query: { projectId: projectId ?? undefined } } })),
  })

export const useSetAssignment = () =>
  useAiMutation((body: AssignmentInput) => unwrap(api.PUT('/api/v1/ai/assignments', { body })), [keys.assignments])

export function resolveProfile(query: { projectId?: string; phase?: string; agentRole?: string }) {
  return unwrap(api.GET('/api/v1/ai/assignments:resolve', { params: { query } }))
}

export const usePolicy = () => useQuery({ queryKey: keys.policy, queryFn: () => unwrap(api.GET('/api/v1/ai/policy')) })

export const useSetPolicy = () =>
  useAiMutation((body: PolicyInput) => unwrap(api.PUT('/api/v1/ai/policy', { body })), [keys.policy, keys.catalog])

// Usage and budgets
export const useUsage = (groupBy: GroupBy, since: string, until: string) =>
  useQuery({
    queryKey: [...keys.usage, groupBy, since, until],
    queryFn: () => unwrap(api.GET('/api/v1/usage/summary', { params: { query: { groupBy, since, until } } })),
    placeholderData: keepPreviousData,
  })

/** The project permission the Costs tab needs (tokens); money also needs cost.view on the tenant, decided by the API. */
export const USAGE_VIEW = 'usage.view'

/** The whole life of one project by phase, agent and model (project usage.view; money with cost.view). */
export const useProjectUsage = (projectId: string, enabled = true) =>
  useQuery({
    queryKey: [...keys.usage, 'project', projectId],
    queryFn: () =>
      unwrap(api.GET('/api/v1/projects/{project_id}/usage', { params: { path: { project_id: projectId } } })),
    enabled,
  })

export const useBudgets = (enabled: boolean) =>
  useQuery({ queryKey: keys.budgets, queryFn: () => unwrap(api.GET('/api/v1/budgets')), enabled })

export const useSaveBudget = () =>
  useAiMutation(
    ({ id, body }: { id: string | null; body: BudgetInput }) =>
      id
        ? unwrap(api.PUT('/api/v1/budgets/{budget_id}', { params: { path: { budget_id: id } }, body }))
        : unwrap(api.POST('/api/v1/budgets', { body })),
    [keys.budgets],
  )

export const useDeleteBudget = () =>
  useAiMutation(
    (id: string) => unwrap(api.DELETE('/api/v1/budgets/{budget_id}', { params: { path: { budget_id: id } } })),
    [keys.budgets],
  )
