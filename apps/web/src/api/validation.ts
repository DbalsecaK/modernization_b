import { useQuery } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// Validation and traceability of a project (spec 11.3, 11.6, 18.x): the verdicts the worker computed by code, their
// proof packs, and rule by rule the legacy lines, the generated files and the behaviour of both sides. Read only: a
// verdict is evidence; a person signs off at gate C4 (Runs tab). Seeing code needs `code.view`.
export type VerdictOut = Schemas['VerdictOut']
export type CheckOut = Schemas['CheckOut']
export type TraceRule = Schemas['TraceRuleOut']
export type TraceDetail = Schemas['TraceDetailOut']
export type CodeExcerpt = Schemas['CodeExcerptOut']
export type TraceCase = Schemas['CaseOut']

/** The project permission the code endpoints (proof pack, traceability) require. */
export const CODE_VIEW = 'code.view'

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

const keys = {
  verdicts: (projectId: string) => ['projects', projectId, 'verdicts'],
  traceability: (projectId: string) => ['projects', projectId, 'traceability'],
  rule: (projectId: string, key: string) => ['projects', projectId, 'traceability', key],
} as const

const path = (projectId: string) => ({ params: { path: { project_id: projectId } } })

/** Newest first. */
export const useVerdicts = (projectId: string) =>
  useQuery({
    queryKey: keys.verdicts(projectId),
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/verdicts', path(projectId))),
  })

/** A plain same-origin link: the browser sends the session cookie and saves the zip (Content-Disposition). */
export const proofPackUrl = (projectId: string, verdictId: string) =>
  `/api/v1/projects/${projectId}/verdicts/${verdictId}/proof-pack`

export const useTraceability = (projectId: string, enabled = true) =>
  useQuery({
    queryKey: keys.traceability(projectId),
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/traceability', path(projectId))),
    enabled,
  })

export const useRuleTrace = (projectId: string, ruleKey: string | null, enabled = true) =>
  useQuery({
    queryKey: keys.rule(projectId, ruleKey ?? ''),
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/projects/{project_id}/traceability/{rule_key}', {
          params: { path: { project_id: projectId, rule_key: ruleKey! } },
        }),
      ),
    enabled: enabled && !!ruleKey,
  })
