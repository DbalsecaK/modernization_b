import type { GraphData, GraphEdge, GraphFlow, GraphNode, GraphScenario, GraphSummary } from '@/api/graph'

// Pure helpers of the knowledge graph for the deep inventory (ADR-0032): blocks inside a unit, grouping by
// transactional phase, the business-flow options (by entry point and by scenario) and the summary header.

export const PHASES = ['pre', 'transaction', 'post', 'error'] as const
export type Phase = (typeof PHASES)[number] | 'none'

/** The select value of a scenario, so its id never collides with an entry-point flow id. */
export const SCENARIO_PREFIX = 'scenario:'

/** CONTAINS links a unit to its blocks: it is structure, never drawn as a line nor counted as a relation. */
export const isDrawable = (e: GraphEdge) => e.kind !== 'CONTAINS'

/** The unit of every child node (block), from its `parent` field or a CONTAINS edge; both ends must exist. */
export function parentsOf(nodes: GraphNode[], edges: GraphEdge[]): Map<string, string> {
  const ids = new Set(nodes.map((n) => n.id))
  const out = new Map<string, string>()
  nodes.forEach((n) => n.parent && n.parent !== n.id && ids.has(n.parent) && out.set(n.id, n.parent))
  edges.forEach(
    (e) => e.kind === 'CONTAINS' && ids.has(e.from) && ids.has(e.to) && !out.has(e.to) && out.set(e.to, e.from),
  )
  return out
}

/** The blocks of a unit, in the order the graph lists them. */
export function childrenOf(unit: string, parents: Map<string, string>): string[] {
  return [...parents].filter(([, p]) => p === unit).map(([id]) => id)
}

/** What the top level shows: every node that is not a block, so the system picture stays as before. */
export function topLevel(nodes: GraphNode[], parents: Map<string, string>): GraphNode[] {
  return nodes.filter((n) => !parents.has(n.id))
}

/** Inside a unit: its blocks plus what they touch (tables, external calls, other units), never other blocks. */
export function unitView(
  unit: string,
  nodes: GraphNode[],
  edges: GraphEdge[],
  parents: Map<string, string>,
): GraphNode[] {
  const blocks = new Set(childrenOf(unit, parents))
  const touched = new Set<string>()
  edges.filter(isDrawable).forEach((e) => {
    if (blocks.has(e.from) && !parents.has(e.to) && e.to !== unit) touched.add(e.to)
    if (blocks.has(e.to) && !parents.has(e.from) && e.from !== unit) touched.add(e.from)
  })
  return nodes.filter((n) => blocks.has(n.id) || touched.has(n.id))
}

export function phaseOf(node: GraphNode): Phase {
  return (PHASES as readonly string[]).includes(node.phase ?? '') ? (node.phase as Phase) : 'none'
}

/** The circle a node goes into: by domain, or (inside a unit) blocks by phase and the rest outside the unit. */
export function groupKeyOf(node: GraphNode, by: 'domain' | 'phase', parents: Map<string, string>): string {
  if (by === 'domain') return node.domain
  return parents.has(node.id) ? `phase:${phaseOf(node)}` : 'outside'
}

/** Blocks grouped by phase in transactional order (before, inside, after, error exits); empty phases left out. */
export function phaseGroups(blocks: GraphNode[]): { phase: Phase; ids: string[] }[] {
  return ([...PHASES, 'none'] as Phase[])
    .map((phase) => ({ phase, ids: blocks.filter((b) => phaseOf(b) === phase).map((b) => b.id) }))
    .filter((g) => g.ids.length > 0)
}

/** The unit to show for a walkthrough step: the unit of its first block; null when the step is at the top level. */
export function unitForStep(stepNodes: string[], parents: Map<string, string>): string | null {
  for (const id of stepNodes) {
    const p = parents.get(id)
    if (p) return p
  }
  return null
}

export type FlowOption = { value: string; label: string }

/** The business-flow select: the entry-point flows and the insight scenarios (name and persona) as two groups. */
export function flowOptions(
  flows: GraphFlow[],
  scenarios: GraphScenario[],
): { entry: FlowOption[]; scenario: FlowOption[] } {
  return {
    entry: flows.map((f) => ({ value: f.id, label: f.name })),
    scenario: scenarios.map((s) => ({
      value: `${SCENARIO_PREFIX}${s.id}`,
      label: s.persona ? `${s.name} · ${s.persona}` : s.name,
    })),
  }
}

/** The summary header: the server's summary, or computed from the top level of the graph when it is absent. */
export function summaryOf(data: GraphData, parents: Map<string, string>): GraphSummary {
  if (data.summary) return data.summary
  const top = topLevel(data.nodes, parents)
  const topIds = new Set(top.map((n) => n.id))
  const entries = new Set(data.flows.map((f) => f.entry))
  return {
    modules: top.filter((n) => n.type !== 'file' && !n.external).length,
    stores: top.filter((n) => n.type === 'file').length,
    relations: data.edges.filter((e) => isDrawable(e) && topIds.has(e.from) && topIds.has(e.to)).length,
    entryPoints: entries.size || top.filter((n) => n.type === 'transaction').length,
  }
}
