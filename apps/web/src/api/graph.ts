import { useQuery } from '@tanstack/react-query'
import { api, sessionHeaders, toApiError, type Schemas } from './client'

// The knowledge graph of a project (spec 5.2, 5.2.1): the code units the inventory found, their relations, the rules
// that cite them, their migration state and the business flows walked from each entry point. Read only; computed by
// the server from the graph written by the worker's inventory.
//
// Deep inventory (M17, ADR-0032): blocks inside each unit (`parent`, `phase`), tables known only from the code
// (`schemaKnown`), the relations between blocks and a summary. Written as optional extensions of the generated types
// so the code compiles before and after `pnpm api:types` picks them up.
/** Where a block sits with respect to the transaction: before, inside, after it, or an exit on error. */
export type BlockPhase = 'pre' | 'transaction' | 'post' | 'error'
export type GraphNode = Schemas['GraphNodeOut'] & {
  /** The unit (procedure, program) this block belongs to; absent on units. */
  parent?: string | null
  /** The transactional phase of a block (`BlockPhase`); other values are shown as "no phase". */
  phase?: string | null
  /** False on tables known only because the code uses them (no DDL in the inputs). */
  schemaKnown?: boolean | null
}
export type GraphEdgeKind = Schemas['GraphEdgeOut']['kind'] | 'NEXT' | 'GOTO' | 'ON_ERROR' | 'CONTAINS'
export type GraphEdge = Omit<Schemas['GraphEdgeOut'], 'kind'> & { kind: GraphEdgeKind }
export type GraphSummary = { modules: number; stores: number; relations: number; entryPoints: number }
export type GraphData = Omit<Schemas['GraphOut'], 'nodes' | 'edges' | 'summary'> & {
  nodes: GraphNode[]
  edges: GraphEdge[]
  summary?: GraphSummary | null
}
export type GraphFlow = Schemas['BusinessFlowOut']
export type Classification = Schemas['ClassificationOut']
export type ClassLabel = Schemas['ClassifiedStatementOut']['label']
export type GraphNodeType = GraphNode['type']
export type MigrationState = GraphNode['state']

type Result<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw toApiError(response, error)
  return data as T
}

export const useGraph = (projectId: string) =>
  useQuery({
    queryKey: ['projects', projectId, 'graph'],
    queryFn: () =>
      unwrap(api.GET('/api/v1/projects/{project_id}/graph', { params: { path: { project_id: projectId } } })),
    retry: false,
  })

/** What may break if the node changes (the server walks the graph, paragraphs and fields included). */
export async function impactOf(projectId: string, node: string, depth = 3): Promise<string[]> {
  const result = await unwrap(
    api.GET('/api/v1/projects/{project_id}/graph/impact', {
      params: { path: { project_id: projectId }, query: { node, depth } },
    }),
  )
  return result.impacted
}

/** The statements of the legacy with their class and why (stored by the classification phase); null before it. */
export const useClassification = (projectId: string) =>
  useQuery({
    queryKey: ['projects', projectId, 'classification'],
    queryFn: () =>
      unwrap(api.GET('/api/v1/projects/{project_id}/classification', { params: { path: { project_id: projectId } } })),
    retry: false,
  })

// Reading aids a model wrote from the code (ADR-0032): descriptions of units and blocks, the architect's observations
// and the business flows by scenario. Not evidence; empty when the run had no `deep_inventory`.
export type ScenarioStep = { title: string; nodes: string[]; rule?: string | null }
export type GraphScenario = {
  id: string
  name: string
  persona?: string | null
  summary?: string | null
  rules: string[]
  steps: ScenarioStep[]
}
export type GraphInsights = {
  descriptions: Record<string, string>
  observations: string[]
  scenarios: GraphScenario[]
}

export const EMPTY_INSIGHTS: GraphInsights = { descriptions: {}, observations: [], scenarios: [] }

const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])

/** Tolerant reading of the insights body: anything missing or malformed counts as empty. */
export function normalizeInsights(body: unknown): GraphInsights {
  if (!body || typeof body !== 'object') return EMPTY_INSIGHTS
  const raw = body as Record<string, unknown>
  const descriptions = Object.fromEntries(
    Object.entries((raw.descriptions ?? {}) as Record<string, unknown>).filter(
      (e): e is [string, string] => typeof e[1] === 'string' && e[1].trim() !== '',
    ),
  )
  const scenarios = (Array.isArray(raw.scenarios) ? raw.scenarios : [])
    .filter((x): x is Record<string, unknown> => !!x && typeof x === 'object')
    .filter((x) => typeof x.id === 'string' && typeof x.name === 'string')
    .map((x) => ({
      id: x.id as string,
      name: x.name as string,
      persona: typeof x.persona === 'string' ? x.persona : null,
      summary: typeof x.summary === 'string' ? x.summary : null,
      rules: strings(x.rules),
      steps: (Array.isArray(x.steps) ? x.steps : [])
        .filter((st): st is Record<string, unknown> => !!st && typeof st === 'object')
        .map((st) => ({
          title: typeof st.title === 'string' ? st.title : '',
          nodes: strings(st.nodes),
          rule: typeof st.rule === 'string' && st.rule ? st.rule : null,
        })),
    }))
  return { descriptions, observations: strings(raw.observations), scenarios }
}

async function fetchInsights(projectId: string): Promise<GraphInsights> {
  // Hand-written until the route is in the generated types.
  const response = await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/graph/insights`, {
    credentials: 'same-origin',
    headers: sessionHeaders('GET'),
  })
  // No insights yet (older API, graph not configured): the graph simply shows without them.
  if (response.status === 404 || response.status === 503) return EMPTY_INSIGHTS
  const body: unknown = await response.json().catch(() => undefined)
  if (!response.ok) throw toApiError(response, body)
  return normalizeInsights(body)
}

export const useGraphInsights = (projectId: string) =>
  useQuery({
    queryKey: ['projects', projectId, 'graph', 'insights'],
    queryFn: () => fetchInsights(projectId),
    retry: false,
  })
