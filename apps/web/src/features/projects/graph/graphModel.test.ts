import { describe, expect, it } from 'vitest'
import type { GraphData, GraphEdge, GraphNode } from '@/api/graph'
import {
  SCENARIO_PREFIX,
  childrenOf,
  flowOptions,
  groupKeyOf,
  isDrawable,
  parentsOf,
  phaseGroups,
  phaseOf,
  summaryOf,
  topLevel,
  unitForStep,
  unitView,
} from './graphModel'

const node = (id: string, extra: Partial<GraphNode> = {}): GraphNode => ({
  id,
  name: id.toUpperCase(),
  type: 'program',
  kind: 'StoredProcedure',
  domain: 'Payments',
  external: false,
  orphan: false,
  file: null,
  parent: null,
  phase: null,
  schemaKnown: null,
  lineStart: null,
  lineEnd: null,
  loc: null,
  rules: [],
  source: null,
  state: 'pending',
  ...extra,
})
const edge = (from: string, kind: GraphEdge['kind'], to: string): GraphEdge => ({ from, kind, to })

// A procedure with three blocks (two by `parent`, one only by a CONTAINS edge), a table and an external call.
const nodes = [
  node('sp'),
  node('sp.b1', { parent: 'sp', phase: 'pre' }),
  node('sp.b2', { parent: 'sp', phase: 'transaction' }),
  node('sp.b3', { phase: 'error' }),
  node('other'),
  node('t1', { type: 'file', kind: 'Table', schemaKnown: false }),
  node('ext', { external: true }),
  node('entry', { type: 'transaction', kind: 'Transaction' }),
]
const edges = [
  edge('sp', 'CONTAINS', 'sp.b1'),
  edge('sp', 'CONTAINS', 'sp.b3'),
  edge('sp.b1', 'NEXT', 'sp.b2'),
  edge('sp.b2', 'ON_ERROR', 'sp.b3'),
  edge('sp.b2', 'WRITES', 't1'),
  edge('sp.b3', 'CALLS', 'ext'),
  edge('sp', 'WRITES', 't1'),
  edge('entry', 'STARTS', 'sp'),
  edge('other', 'READS', 't1'),
]
const parents = parentsOf(nodes, edges)

describe('children of a unit', () => {
  it('come from the parent field and from CONTAINS edges', () => {
    expect(childrenOf('sp', parents).sort()).toEqual(['sp.b1', 'sp.b2', 'sp.b3'])
    expect(childrenOf('other', parents)).toEqual([])
  })

  it('ignore a parent that is not in the graph', () => {
    expect(parentsOf([node('a', { parent: 'missing' })], []).size).toBe(0)
  })

  it('are hidden at the top level, which keeps every other node', () => {
    expect(topLevel(nodes, parents).map((n) => n.id)).toEqual(['sp', 'other', 't1', 'ext', 'entry'])
  })

  it('inside the unit come with what they touch, never the unit itself', () => {
    expect(
      unitView('sp', nodes, edges, parents)
        .map((n) => n.id)
        .sort(),
    ).toEqual(['ext', 'sp.b1', 'sp.b2', 'sp.b3', 't1'])
  })

  it('CONTAINS is never drawn', () => {
    expect(edges.filter(isDrawable).some((e) => e.kind === 'CONTAINS')).toBe(false)
  })
})

describe('grouping by phase', () => {
  const blocks = nodes.filter((n) => parents.has(n.id))

  it('orders the phases as the transaction runs and leaves empty ones out', () => {
    expect(phaseGroups(blocks)).toEqual([
      { phase: 'pre', ids: ['sp.b1'] },
      { phase: 'transaction', ids: ['sp.b2'] },
      { phase: 'error', ids: ['sp.b3'] },
    ])
  })

  it('treats an unknown phase as no phase', () => {
    expect(phaseOf(node('x', { phase: 'weird' as GraphNode['phase'] }))).toBe('none')
    expect(phaseOf(node('x'))).toBe('none')
  })

  it('puts blocks in their phase circle and the rest outside the unit', () => {
    expect(groupKeyOf(nodes[1], 'phase', parents)).toBe('phase:pre')
    expect(groupKeyOf(nodes[6], 'phase', parents)).toBe('outside')
    expect(groupKeyOf(nodes[1], 'domain', parents)).toBe('Payments')
  })
})

describe('walkthrough steps over blocks', () => {
  it('enter the unit of the first block of the step', () => {
    expect(unitForStep(['t1', 'sp.b2'], parents)).toBe('sp')
    expect(unitForStep(['entry', 'sp'], parents)).toBeNull()
  })
})

describe('business-flow options', () => {
  const flows: GraphData['flows'] = [{ id: 'f1', name: 'Pay a bill', entry: 'entry', rules: [], steps: [] }]

  it('list entry-point flows and scenarios apart, scenarios with their persona', () => {
    const options = flowOptions(flows, [
      { id: 's1', name: 'Late payment', persona: 'Teller', rules: [], steps: [] },
      { id: 'f1', name: 'Same id', persona: null, rules: [], steps: [] },
    ])
    expect(options.entry).toEqual([{ value: 'f1', label: 'Pay a bill' }])
    expect(options.scenario).toEqual([
      { value: `${SCENARIO_PREFIX}s1`, label: 'Late payment · Teller' },
      { value: `${SCENARIO_PREFIX}f1`, label: 'Same id' },
    ])
  })

  it('have no scenario group without insights', () => {
    expect(flowOptions(flows, []).scenario).toEqual([])
  })
})

describe('summary header', () => {
  const data: GraphData = { nodes, edges, rules: [], flows: [] }

  it('uses the server summary when there is one', () => {
    const summary = { modules: 9, stores: 8, relations: 7, entryPoints: 6 }
    expect(summaryOf({ ...data, summary }, parents)).toEqual(summary)
  })

  it('falls back to counting the top level without blocks, CONTAINS or external calls', () => {
    expect(summaryOf(data, parents)).toEqual({ modules: 3, stores: 1, relations: 3, entryPoints: 1 })
  })

  it('counts entry points from the flows when there are flows', () => {
    const flows: GraphData['flows'] = [
      { id: 'a', name: 'A', entry: 'entry', rules: [], steps: [] },
      { id: 'b', name: 'B', entry: 'other', rules: [], steps: [] },
    ]
    expect(summaryOf({ ...data, flows }, parents).entryPoints).toBe(2)
  })
})
