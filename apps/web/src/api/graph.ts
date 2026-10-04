import { useQuery } from '@tanstack/react-query'
import { api, toApiError, type Schemas } from './client'

// The knowledge graph of a project (spec 5.2, 5.2.1): the code units the inventory found, their relations, the rules
// that cite them, their migration state and the business flows walked from each entry point. Read only; computed by
// the server from the graph written by the worker's inventory.
export type GraphData = Schemas['GraphOut']
export type GraphNode = Schemas['GraphNodeOut']
export type GraphEdge = Schemas['GraphEdgeOut']
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
