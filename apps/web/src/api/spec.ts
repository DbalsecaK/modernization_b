import { useEffect, useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// The specification of a project (spec 7.7): business rules extracted by the agents, the user stories people review,
// the coverage and C1 readiness, and the migration plan by waves. Every check (Gherkin, coverage, plan dependencies)
// is computed by the server's deterministic code; the web only shows the result and sends the person's changes.
export type RuleOut = Schemas['nexti_api__spec__schemas__RuleOut']
export type StoryOut = Schemas['StoryOut']
export type StoryInput = Schemas['StoryIn']
export type Coverage = Schemas['CoverageOut']
export type C1Check = Schemas['C1CheckOut']
export type PlanOut = Schemas['PlanOut']
export type PlanProblem = Schemas['PlanProblemOut']
export type GherkinResult = Schemas['GherkinOut']
export type GherkinProblem = Schemas['GherkinProblemOut']

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

const keys = {
  spec: (projectId: string) => ['projects', projectId, 'spec'],
  rules: (projectId: string) => ['projects', projectId, 'spec', 'rules'],
  ruleVersions: (projectId: string, key: string) => ['projects', projectId, 'spec', 'rules', key, 'versions'],
  stories: (projectId: string) => ['projects', projectId, 'spec', 'stories'],
  storyVersions: (projectId: string, key: string) => ['projects', projectId, 'spec', 'stories', key, 'versions'],
  coverage: (projectId: string) => ['projects', projectId, 'spec', 'coverage'],
  c1: (projectId: string) => ['projects', projectId, 'spec', 'c1'],
  plan: (projectId: string) => ['projects', projectId, 'spec', 'plan'],
} as const

const path = (projectId: string) => ({ params: { path: { project_id: projectId } } })
const storyPath = (projectId: string, key: string) => ({ params: { path: { project_id: projectId, key } } })

/** Any change to a story or the plan can change coverage, C1 readiness and the plan: refresh the whole spec. */
function useSpecMutation<A, R>(projectId: string, fn: (args: A) => Promise<R>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => client.invalidateQueries({ queryKey: keys.spec(projectId) }),
  })
}

// Rules
export const useRules = (projectId: string) =>
  useQuery({
    queryKey: keys.rules(projectId),
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/spec/rules', path(projectId))),
  })

export const useRuleVersions = (projectId: string, key: string | null) =>
  useQuery({
    queryKey: keys.ruleVersions(projectId, key ?? ''),
    queryFn: () =>
      unwrap(api.GET('/api/v1/projects/{project_id}/spec/rules/{key}/versions', storyPath(projectId, key!))),
    enabled: !!key,
  })

// Stories
export const useStories = (projectId: string) =>
  useQuery({
    queryKey: keys.stories(projectId),
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/stories', path(projectId))),
  })

export const useStoryVersions = (projectId: string, key: string | null) =>
  useQuery({
    queryKey: keys.storyVersions(projectId, key ?? ''),
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/stories/{key}/versions', storyPath(projectId, key!))),
    enabled: !!key,
  })

export const useCreateStory = (projectId: string) =>
  useSpecMutation(projectId, (body: StoryInput) =>
    unwrap(api.POST('/api/v1/projects/{project_id}/stories', { ...path(projectId), body })),
  )

export const useUpdateStory = (projectId: string) =>
  useSpecMutation(projectId, ({ key, body }: { key: string; body: StoryInput }) =>
    unwrap(api.PUT('/api/v1/projects/{project_id}/stories/{key}', { ...storyPath(projectId, key), body })),
  )

export const useSplitStory = (projectId: string) =>
  useSpecMutation(projectId, ({ key, body }: { key: string; body: Schemas['SplitIn'] }) =>
    unwrap(api.POST('/api/v1/projects/{project_id}/stories/{key}:split', { ...storyPath(projectId, key), body })),
  )

/** `key` is absorbed by `into`. */
export const useMergeStory = (projectId: string) =>
  useSpecMutation(projectId, ({ key, into }: { key: string; into: string }) =>
    unwrap(
      api.POST('/api/v1/projects/{project_id}/stories/{key}:merge', { ...storyPath(projectId, key), body: { into } }),
    ),
  )

export const useDiscardStory = (projectId: string) =>
  useSpecMutation(projectId, ({ key, body }: { key: string; body: Schemas['DiscardIn'] }) =>
    unwrap(api.POST('/api/v1/projects/{project_id}/stories/{key}:discard', { ...storyPath(projectId, key), body })),
  )

export const useRestoreStory = (projectId: string) =>
  useSpecMutation(projectId, (key: string) =>
    unwrap(api.POST('/api/v1/projects/{project_id}/stories/{key}:restore', storyPath(projectId, key))),
  )

export const useAddDependency = (projectId: string) =>
  useSpecMutation(projectId, ({ key, body }: { key: string; body: Schemas['DependencyIn'] }) =>
    unwrap(
      api.POST('/api/v1/projects/{project_id}/stories/{key}/dependencies', { ...storyPath(projectId, key), body }),
    ),
  )

export const useRemoveDependency = (projectId: string) =>
  useSpecMutation(projectId, ({ key, on }: { key: string; on: string }) =>
    unwrap(
      api.DELETE('/api/v1/projects/{project_id}/stories/{key}/dependencies/{on}', {
        params: { path: { project_id: projectId, key, on } },
      }),
    ),
  )

// Coverage and C1 readiness
export const useCoverage = (projectId: string) =>
  useQuery({
    queryKey: keys.coverage(projectId),
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/coverage', path(projectId))),
  })

export const useC1Check = (projectId: string) =>
  useQuery({
    queryKey: keys.c1(projectId),
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/c1-check', path(projectId))),
  })

// Plan by waves (404 `plan_not_found` until the pipeline derives the stories)
export const usePlan = (projectId: string) =>
  useQuery({
    queryKey: keys.plan(projectId),
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/plan', path(projectId))),
    retry: false,
  })

/** A hard dependency violation is rejected (422 `invalid_plan` with its problems); a soft one saves with warnings. */
export const useSavePlan = (projectId: string) =>
  useSpecMutation(projectId, (body: Schemas['PlanIn']) =>
    unwrap(api.PUT('/api/v1/projects/{project_id}/plan', { ...path(projectId), body })),
  )

export const useResetPlan = (projectId: string) =>
  useSpecMutation(projectId, () => unwrap(api.POST('/api/v1/projects/{project_id}/plan:reset', path(projectId))))

// Gherkin
export function validateGherkin(criteria: string[]): Promise<GherkinResult> {
  return unwrap(api.POST('/api/v1/gherkin:validate', { body: { criteria } }))
}

/** The value after it stopped changing for `delay` ms. */
export function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

export const GHERKIN_DEBOUNCE_MS = 400

/**
 * The server's Gherkin validation of some criteria (the same code that guards saving). With `debounce`, it waits for
 * the person to stop typing. `current` says whether the result belongs to the criteria given (not an older text).
 */
export function useGherkin(criteria: string[], { debounce = 0, enabled = true } = {}) {
  const joined = JSON.stringify(criteria)
  const settled = useDebounced(joined, debounce)
  const query = useQuery({
    queryKey: ['gherkin', settled],
    queryFn: () => validateGherkin(JSON.parse(settled) as string[]),
    enabled: enabled && criteria.length > 0,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  })
  return { ...query, current: settled === joined && !query.isPlaceholderData && !query.isFetching }
}
